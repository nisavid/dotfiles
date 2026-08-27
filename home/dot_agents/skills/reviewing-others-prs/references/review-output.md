# Review Output

Use for GitHub comments, re-review ledgers, approval/request-changes recommendations, thread resolutions, and pause packets.

Ledger items use `pr-review-orchestration` categories and record reviewer, URL, topic or file, synopsis, ownership, category, evidence, action, verification, and draft text. For re-reviews, split own threads, contextual reviewer threads, new findings, and check/bot blockers.

Lead with severity-ordered findings. Each finding needs file:line, impact, current-head evidence, and the smallest author-owned remedy. If no finding survives, say so and name residual gaps such as skipped tests, unavailable deployment context, generated code not inspected, or unchanged prior threads.

GitHub comments should include exact text and location. Keep them terse, direct, and thread-scoped. Avoid CLI instructions, implementation essays, praise, or unrelated context.

## Comment Voice

A comment is a reviewer continuing the conversation, so open with the finding itself—or, when part of the change is genuinely right, with that ("The blocking wait makes sense here—I don't want to put the per-request polling back on the runner path"). Name what you personally verified and what remains unchecked: "I couldn't find a production caller using the direct form, but `--processor` is still an extension point."

A confidently raised issue has three ingredients: the armed footgun stated as a plain declarative, the smallest remedy asked as one question that leaves the author agency, and the reason that remedy disarms the specific failure. Arrange them differently per comment—identical arrangement across a batch reads as machine output. One approved shape:

> `numRows: null` means "unknown," but `?? 0` persists it as "empty." Could we leave `size` unset in that case and only construct a `BigInt` for an actual count? The schema already gives us an unknown state; preserving it here avoids handing downstream code a confidently wrong zero.

An ask sits between a command and a plea: an opinionated declarative ("I think we can remove the follower fanout") or a single question—one ask per comment. Prefer a vivid concrete consequence ("a transient request failure stays a request failure") to a hedge. Thread register is the shortest phrasing that still sounds like speech: fragments are fine ("`retry: false` here?"); compression the reader must decode is not. Headings on findings name the acceptable outcome ("Keep direct processor calls cancellable, or document the exception"), not an abstract noun.

A review summary that restates the inline comments is redundant; give a verdict, the blocking findings, and residual gaps.

Separate review confidence from merge readiness. A clean review does not prove the PR is mergeable.

If actuation is not authorized, provide findings, draft comments, ledger summary, verification run or skipped, and explicit next actions for Ivan.
