---
name: writing-reviewable-pr-descriptions
description: Use when writing or updating PR descriptions, pull request bodies, GitHub PR bodies, review summaries, PR text, demo sections, screenshots, media cards, link-heavy bodies, access notes, caveats, or lossy rewrite risks.
---

# Writing Reviewable PR Descriptions

## Core Principle

A PR description is reviewer navigation, not an essay or changelog dump. It should make the review path obvious: should I review now, where do I start, what changed, how was it verified, and what remains?

## Audience Order

Optimize for:

1. **Reviewers:** safe, efficient review path through the PR.
2. **Observers:** enough context to comment.
3. **Author:** memory refresh and loose-end checklist.

If a detail does not help review timing, order, risk focus, or merge readiness, shorten it or move it lower.

## Default Shape

Choose the smallest shape that answers reviewer questions:

- **Tiny PRs:** 1-3 bullets plus verification, or a short paragraph if that scans faster. Omit shields, reviewer maps, architecture, dependencies, and blockers unless they matter.
- **Straightforward PRs:** Use short sections: `Summary`, `Changes`, `Verification`, and `Follow-up` or `Blockers` only when real. Prefer bullets over paragraphs.
- **Large, stacked, cross-cutting, reviewer-heavy, or readiness-ambiguous PRs:** Consult `large-pr-description-example.md` as a non-copy example, then write the smallest description that covers real review needs.

Compact default: `Summary`, `Changes`, and `Verification`, each as short bullets. Add `Review Path`, `Blockers`, or `Follow-up` only when reviewers need them.

For large PRs, consider these first-viewport elements and include only the ones that represent real review needs:

1. Optional unheaded Shields.io rows: review gates, architecture, contracts.
2. One-line story naming workflow, inputs, outputs, and core architecture.
3. GFM alert only when a real gate, risk, or review hold exists.
4. Dependencies, only when there are real base PRs, companion PRs, required artifacts, rollout gates, or likely-changing areas.
5. Reviewer map, only when review order matters, grouped by contract boundary rather than commit order.

Then add only the sections reviewers need: summary, architecture/contracts, concrete change groups, media, triage/rationale, verification, current status, PR readiness blockers, and story follow-up.

## Scannability And Links

- Lead with bullets when listing facts, changes, risks, checks, or follow-up.
- Keep paragraphs short: one idea, usually 1-3 sentences.
- Link every actionable reference reviewers may want to open: PRs, issues, CI jobs, docs, generated artifacts, files, directories, screenshots, recordings, dashboards, and external specs.
- In GitHub PR bodies, do not use bare file links such as `(services/api/src/routes.ts)`; they resolve relative to the PR URL and break.
- For changed files in review paths, prefer Files changed tab links so reviewers land where they can comment: `https://github.com/OWNER/REPO/pull/PR_NUMBER/files#diff-SHA256_PATH_HASH`. GitHub file-diff anchors use the SHA-256 hash of the changed file path. Keep the visible text as the path.
- Use `blob/HEAD_SHA/...` or `tree/HEAD_SHA/...` links only for supporting references that are not changed files being reviewed.
- In review paths, use nested file-link lists when a group has multiple or long references. Avoid comma-separated inline runs of long paths; they become hard to scan and click.
- Keep commands in code spans rather than links.
- If a section becomes a wall of prose, convert it to bullets or split it by review boundary.
- Headings should name the reviewer-relevant surface, not the description strategy. Use `Changes` with grouped bullets when the list is small, or concrete boundary headings such as `API Contracts`, `Worker Lifecycle`, or `Admin UI` when the PR needs separate sections.

## Scope And Evidence

- Determine PR scope from the platform's PR file list when possible: `gh pr diff --name-only` or `gh pr view --json files --jq '.files[].path'`.
- Decide whether the description is for the pushed PR or for local pending branch changes. Prefer the pushed PR diff for published PR bodies; if local changes are included, state that explicitly or push first.
- For existing PRs, fetch the live GitHub body immediately before any body edit, usually with `gh pr view <pr-or-branch> --json body --jq .body`. Treat that live body as the preservation baseline, not disposable source material.
- Preserve still-current custom, user-authored, or user-requested sections unless the user explicitly asks to remove them or they are clearly stale or superseded. This includes demo/media cards, screenshots, image links, recordings, demo links, captions, access notes, passwords or temporary access details, issue or doc links, caveats, and review instructions.
- When replacing or shortening a section, carry forward its still-current details into the replacement. If a section's preservation status is ambiguous, keep and tighten it or ask before removing it.
- Remove stale status, blockers, review paths, verification claims, and leftover template text only after separating them from still-current custom material.
- Before `gh pr edit`, compare the live baseline body with the proposed body and explicitly audit for unintended deletion of links, images, custom headings, demo/media sections, captions, access notes/passwords, issue references, caveats, and review instructions.
- After `gh pr edit`, verify the stored body with `gh pr view <pr> --json body`. If the stored body differs from the intended body or the preservation audit fails, repair it before reporting completion.
- Use file lists to bound scope, then inspect the actual diff or commit range before summarizing behavior. Do not write the PR story from filenames alone.
- When a PR exists, read its base branch with `gh pr view --json baseRefName --jq .baseRefName`.
- Before using local `HEAD` for a published PR body, verify it matches the pushed PR head with `gh pr view --json headRefOid --jq .headRefOid` and `git rev-parse HEAD`. If they differ, push first, use `gh pr diff`, or clearly state the body describes local pending changes.
- Check for uncommitted local changes before drafting from local state. Do not let dirty-tree changes appear in a published PR description unless they are pushed or explicitly labeled as pending.
- For local diff stats, explicitly update the remote-tracking base ref first, then inspect `BASE_BRANCH=$(gh pr view --json baseRefName --jq .baseRefName)`, `git fetch origin "+refs/heads/$BASE_BRANCH:refs/remotes/origin/$BASE_BRANCH"`, and `git diff --name-status "$(git merge-base "origin/$BASE_BRANCH" HEAD)" HEAD`.
- When no PR exists, ask for the intended base or state the assumed base before using a local merge-base diff.
- Do not infer scope from `origin/$BASE_BRANCH..HEAD` when the branch may not be based directly on the remote base or that ref may be stale.
- If the real diff is smaller than an initial broad scan suggests, rewrite the description around the real diff. Do not carry unrelated files, generated churn, or neighboring branch work into the review path.
- Summarize passing CI instead of listing every passing check. A sentence such as "GitHub checks are passing" is enough unless a specific check is failing, pending, flaky, newly relevant, or useful to open.
- Verify current GitHub check state with `gh pr checks` or `gh pr view --json statusCheckRollup` before claiming checks are passing.
- Do not link-dump passing checks. Link the PR checks page or individual jobs only when that helps reviewers investigate a failure, pending gate, or unusual validation result.
- Phrase verification as command plus result: `` `yarn typecheck` passed ``. Do not attribute routine verification to a person unless authorship is important to the review.
- Mention working directories for commands that are not run from the repository root.

## Acceptance Criteria

A reviewable PR description passes only when:

- The body is proportional to the PR size. Straightforward PRs stay compact; large PR structure appears only when it helps reviewers.
- Reviewers can scan the description quickly through bullets, short sections, and concrete headings.
- Changes are grouped by interface or responsibility boundary, not package list, and the headings name the actual boundary rather than the grouping taxonomy.
- Verification names checks run, skipped checks, failures, and not-yet-run checks when they affect reviewer confidence. Large PRs should separate current GitHub checks from local checks.
- Remaining work is split by scope when both exist: PR readiness blockers before this PR is done, and story/epic follow-up that belongs outside this PR.
- Reviewer-facing references are clickable when GitHub can link them.
- Existing PR updates preserve still-current custom sections, media, links, access notes, captions, caveats, and review instructions from the live body unless removal was explicit or clearly required by current facts.
- The body avoids local paths, transient scratch artifacts, and author-only notes.

For large, stacked, cross-cutting, reviewer-heavy, or readiness-ambiguous PRs, it also passes only when:

- Any included first-viewport elements make review readiness, automated checks, local/manual validation status, review hold, dependencies, and review order obvious. Badges, alerts, dependency rows, and reviewer maps are optional and should appear only when they add reviewer value.
- Dependencies identify actual base PRs, companion PRs, required artifacts, blockers, and likely-changing areas. Omit empty categories such as "no companion PRs" unless reviewers are likely to assume one exists.
- The reviewer map gives a boundary-based path through the diff.
- Architecture/contracts explain ownership, data flow, lifecycle, and visible behavior.

## Rules

- **REQUIRED SUB-SKILL:** Use `resolving-workflow-ownership` when PR status,
  readiness, approval, gate, merge, deploy, release, or closeout wording depends
  on whether the agent, reviewer, operator, code owner, or another owner decides
  or acts. Apply its language policy; do not copy its ownership table here.
- When first-viewport status needs a compact summary, prefer shields over a Markdown `Status Snapshot` table.
- Do not add agent-ledger sections like `Review Readiness` when the same information fits naturally in badges, alerts, dependencies, verification, current status, or blockers.
- Say `review`, not `human review`.
- Prefer bullets over prose for multi-item content. Use tables only when relationships are easier to read in rows and columns than bullets.
- Omit optional sections when they do not help reviewers. Do not add `None`, `N/A`, or negative rows unless the absence resolves a likely reviewer question.
- Include `Current Status` only when it adds information not already visible in the first viewport.
- Include `PR Readiness Blockers` only when concrete blockers remain.
- State PR readiness or mergeability directly only when the readiness owner has
  decided it or the agent owns that decision. Otherwise report evidence and the
  remaining decision, approval, or action owner without implying readiness.
- Do not define design choices by what they reject. Prefer `storage: append-only event log` over `not legacy storage`.
- For stacked or companion PRs, state the base branch or PR, review order, whether this PR is reviewable now, and which diff areas may change.
- Use small interface or interaction diagrams when they reduce cognitive load.
- State when a draft PR is not ready for review.
- Do not publish template instruction text, placeholder headings, or angle-bracket placeholders.

## Ralph Review

For large, stacked, cross-cutting, reviewer-heavy, or readiness-ambiguous draft PRs, request review with `requesting-code-review` and repeat with `ralph-review-until-clean` before publishing. Do not inline weaker substitutes.

- Ask for Critical, Important, and Minor findings focused on reviewer utility, proportionality, scannability, link usefulness, readiness clarity, dependency accuracy, review path, architecture/contracts, verification, remaining-work scope, and first-viewport format.
- Evaluate returned findings with `receiving-code-review`, revise valid ones, and repeat labeled cycles with `ralph-review-until-clean` until the latest review has no actionable findings.
