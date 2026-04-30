---
name: writing-reviewable-pr-descriptions
description: Use when creating or revising pull request descriptions for large, draft, cross-cutting, stacked, or reviewer-heavy PRs where status, dependencies, review order, architecture, verification, or pending work must be clear.
---

# Writing Reviewable PR Descriptions

## Core Principle

A large-PR description is a reviewer aid, not a changelog dump. It answers: should I review now, what does it depend on, where should I start, what changed, how was it verified, and what remains?

**REQUIRED REVIEW SUB-SKILLS:** When the PR description meets the Ralph Review threshold below, use `requesting-code-review` to dispatch the reviewer, `receiving-code-review` to evaluate findings, and `ralph-review-until-clean` for repeat-until-clean semantics. For small description edits, apply this skill directly unless the user explicitly asks for review.

## Audience Order

Optimize for:

1. **Reviewers:** safe, efficient review path through a large diff.
2. **Observers:** enough context to comment.
3. **Author:** memory refresh and loose-end checklist.

If a detail does not help review timing, order, risk focus, or merge readiness, shorten it or move it lower.

## Default Shape

For tiny PRs, do not inflate the body with shields, reviewer maps, or architecture sections. Use a short summary, verification, and blockers or follow-up only when they help review.

For non-tiny PRs, start from `templates/large-pr-description.md`. Preserve the first viewport:

1. Unheaded Shields.io rows: review gates, architecture, contracts.
2. One-line story naming workflow, inputs, outputs, and core architecture.
3. GFM alert only when a real gate, risk, or review hold exists.
4. Dependencies, only when there are real base PRs, companion PRs, required artifacts, rollout gates, or likely-changing areas.
5. Reviewer map grouped by contract boundary, not commit order.

Then add summary, architecture/contracts, boundary-grouped changes, media, triage/rationale, verification, current status, PR readiness blockers, and story follow-up when they help reviewers.

## Acceptance Criteria

A reviewable large-PR description passes only when:

- The first viewport makes review readiness, automated checks, local/manual validation status, review hold, dependencies, and review order obvious through badges, alert text, dependency rows, and the reviewer map.
- Dependencies identify actual base PRs, companion PRs, required artifacts, blockers, and likely-changing areas. Omit empty categories such as "no companion PRs" unless reviewers are likely to assume one exists.
- The reviewer map gives a boundary-based path through the diff.
- Architecture/contracts explain ownership, data flow, lifecycle, and visible behavior.
- Changes are grouped by interface or responsibility boundary, not package list.
- Verification separates current GitHub checks, local checks, skipped checks, failures, and not-yet-run checks.
- Remaining work is split by scope: PR readiness blockers before this PR is done, and story/epic follow-up that belongs outside this PR.
- The body avoids local paths, transient scratch artifacts, and author-only notes.

## Rules

- **REQUIRED SUB-SKILL:** Use `resolving-workflow-ownership` when PR status,
  readiness, approval, gate, merge, deploy, release, or closeout wording depends
  on whether the agent, reviewer, operator, code owner, or another owner decides
  or acts. Apply its language policy; do not copy its ownership table here.
- Use shields, not a Markdown `Status Snapshot` table, for large or reviewer-heavy PRs.
- Do not add agent-ledger sections like `Review Readiness` when the same information fits naturally in badges, alerts, dependencies, verification, current status, or blockers.
- Say `review`, not `human review`.
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

## Ralph Review

For large, stacked, cross-cutting, reviewer-heavy, or readiness-ambiguous draft PRs, run subagent Ralph review before publishing. Apply `requesting-code-review`, `receiving-code-review`, and `ralph-review-until-clean`; do not inline weaker substitutes.

1. Give the subagent the PR body, the audience order, and the acceptance criteria above.
2. Ask for Critical, Important, and Minor findings focused on reviewer utility, readiness clarity, dependency accuracy, review path, architecture/contracts, verification, remaining-work scope, and first-viewport format.
3. Evaluate and revise findings using `receiving-code-review`.
4. Continue labeled Ralph cycles until the latest review has no actionable findings.
