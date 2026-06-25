# Review Output

Use for GitHub comments, re-review ledgers, approval/request-changes recommendations, thread resolutions, and pause packets.

Ledger items use `pr-review-orchestration` categories and record reviewer, URL, topic or file, synopsis, ownership, category, evidence, action, verification, and draft text. For re-reviews, split own threads, contextual reviewer threads, new findings, and check/bot blockers.

Lead with severity-ordered findings. Each finding needs file:line, impact, current-head evidence, and the smallest author-owned remedy. If no finding survives, say so and name residual gaps such as skipped tests, unavailable deployment context, generated code not inspected, or unchanged prior threads.

GitHub comments should include exact text and location. Keep them terse, direct, and thread-scoped. Avoid CLI instructions, implementation essays, praise, or unrelated context.

Separate review confidence from merge readiness. A clean review does not prove the PR is mergeable.

If actuation is not authorized, provide findings, draft comments, ledger summary, verification run or skipped, and explicit next actions for Ivan.
