# Review Output

Use for GitHub comments, re-review ledgers, approval/request-changes recommendations, thread resolutions, and pause packets.

Ledger items use `pr-review-orchestration` categories and record reviewer, URL, topic or file, synopsis, ownership, category, evidence, action, verification, and draft text. For re-reviews, split own threads, contextual reviewer threads, new findings, and check/bot blockers.

Lead with severity-ordered findings. Each finding needs file:line, impact, current-head evidence, and the smallest author-owned remedy. If no finding survives, say so and name residual gaps such as skipped tests, unavailable deployment context, generated code not inspected, or unchanged prior threads.

GitHub comments should include exact text and location. Keep them terse, direct, and thread-scoped. Avoid CLI instructions, implementation essays, freestanding praise, or unrelated context.

## Comment Voice

The global Writing register applies; this section adds the thread shape. A comment continues the conversation on the author's work, so open with the finding itself or with what the change genuinely gets right ("The blocking wait makes sense here. I don't want to put the per-request polling back on the runner path."). Name what you verified and what remains unchecked: "I couldn't find a production caller using the direct form, but `--processor` is still an extension point."

A confidently raised issue names the failure plainly with its concrete consequence, asks for the smallest remedy as a question the author can decline, and says why that remedy closes the specific failure path, in whatever order and proportion the content wants. One shape among many:

> `numRows: null` means "unknown", but `?? 0` persists it as "empty". Could we leave `size` unset in that case and only construct a `BigInt` for an actual count? The schema already gives us an unknown state; preserving it here avoids handing downstream code a confidently wrong zero.

One ask per comment, and say plainly what kind of change it asks for and whether behavior visibly changes. Label a non-blocking aside as one ("Nit: `onClick` is typed as `() => void`; `if (onClick)` is enough."). Fragments that read as speech are welcome ("`retry: false` here?"). The one heading a comment earns is a finding title naming the acceptable outcome ("Keep direct processor calls cancellable, or document the exception"), optionally severity-tagged (**[P2]**); everything else stays paragraphs.

A review summary gives the verdict, the blocking findings, and residual gaps; the inline comments are already visible. A re-review verdict opens with what the new head resolved, then the remainder. When reversing a posted position, say so and give the reason.

Separate review confidence from merge readiness. A clean review does not prove the PR is mergeable.

If actuation is not authorized, provide findings, draft comments, ledger summary, verification run or skipped, and explicit next actions for Ivan.
