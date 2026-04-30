![Status: <Draft|Ready>](https://img.shields.io/badge/status-<draft|ready>-<color>?style=flat-square&labelColor=3F3F46) ![Checks: <Green|Failing|Pending>](https://img.shields.io/badge/checks-<green|failing|pending>-<color>?style=flat-square&labelColor=3F3F46) ![Validation: <Passed|Partial|Pending>](https://img.shields.io/badge/validation-<passed|partial|pending>-<color>?style=flat-square&labelColor=3F3F46) ![Review: <Open|Hold>](https://img.shields.io/badge/review-<open|hold>-<color>?style=flat-square&labelColor=3F3F46)  
![<Architecture Slot>: <Choice>](https://img.shields.io/badge/<slot>-<choice>-<color>?style=flat-square&labelColor=3F3F46) ![<Architecture Slot>: <Choice>](https://img.shields.io/badge/<slot>-<choice>-<color>?style=flat-square&labelColor=3F3F46) ![<Architecture Slot>: <Choice>](https://img.shields.io/badge/<slot>-<choice>-<color>?style=flat-square&labelColor=3F3F46)  
![<Contract Slot>: <Choice>](https://img.shields.io/badge/<slot>-<choice>-<color>?style=flat-square&labelColor=3F3F46) ![<Contract Slot>: <Choice>](https://img.shields.io/badge/<slot>-<choice>-<color>?style=flat-square&labelColor=3F3F46) ![<Contract Slot>: <Choice>](https://img.shields.io/badge/<slot>-<choice>-<color>?style=flat-square&labelColor=3F3F46)

Use URL-encoded badge text (`%20` for spaces, `%2F` for slashes). Omit the validation badge when local/manual validation does not apply, unless that absence is itself useful to reviewers. Prefer green `2EA44F` for passing/ready, yellow `DBAB09` for pending/partial/required, red `CF222E` for failing/blocked, purple `8250DF` for architecture choices, blue `0969DA` for contracts, and gray `6E7781` for explicitly out-of-scope items only when reviewers are likely to expect that area to be in scope.

One sentence naming the workflow, major inputs, major outputs, and core architecture or semantic correction.

> [!WARNING]
> Use only when review is gated. State the exact hold, risk, or required validation.

## Dependencies

Omit this section when there are no real base PRs, companion PRs, required artifacts, rollout gates, or likely-changing areas. Do not add negative rows such as "No companion PRs."

| Dependency | Status | Why this PR depends on it |
| --- | --- | --- |
| [owner/repo#123](https://github.com/owner/repo/pull/123) | Draft/ready/merged | Contract, runtime, migration, deployment, or review-order dependency |

## Reviewer Map

| Pass | Start with | What to check |
| --- | --- | --- |
| 1 | Shared contracts/API surface | Semantics, compatibility, capability gates, ownership boundaries |
| 2 | Core implementation | Business logic, state transitions, cleanup, visible behavior |
| 3 | Integration/runtime boundary | Orchestration, credentials, failure behavior, dependent systems |
| 4 | Presentation/consumer-facing behavior | Intent collection, state reflection, user-facing edge cases |

## Summary

Explain the story in two or three short paragraphs. Name the most important design decision or semantic correction explicitly.

## Architecture

Use a compact table and, when helpful, a small Mermaid diagram. Explain boundaries, interfaces, ownership, lifecycle, and data flow.

## <Change Cluster>

Group changes by review boundary or contract, not by package list or commit order.

## Screenshots / Media

Include screenshots, before/after tables, or recordings for UI/UX changes. Omit this section when not relevant.

## Triage / Rationale

Summarize adopted, replaced, discarded, and deferred alternatives when reviewers need that context.

## Verification

Separate current GitHub checks from local checks. Name skipped, failing, or not-yet-run checks with reasons.

## Current Status

Use only when this adds multi-sentence nuance not already visible in the first viewport, such as `ready for API review, held on runtime validation`.

## PR Readiness Blockers

Omit this section when there are no blockers. Otherwise list concrete tasks, validation inputs, or cleanup items required before this PR is ready for review, complete, or mergeable.

## Story Follow-Up

Omit this section when there is no known follow-up. Otherwise list known release, rollout, promotion, or broader story/epic work that does not belong in this PR.
