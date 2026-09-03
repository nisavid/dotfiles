# Review Output

Use for GitHub comments, re-review ledgers, approval/request-changes recommendations, thread resolutions, and pause packets.

Ledger items use `pr-review-orchestration` categories and record reviewer, URL, topic or file, synopsis, ownership, category, evidence, action, verification, and draft text. For re-reviews, split own threads, contextual reviewer threads, new findings, and check/bot blockers.

Lead with severity-ordered findings. Each finding needs file:line, impact, current-head evidence, and the smallest author-owned remedy. If no finding survives, say so and name residual gaps such as skipped tests, unavailable deployment context, generated code not inspected, or unchanged prior threads.

GitHub comments should include exact text and location. Keep them terse, direct, and thread-scoped. Avoid CLI instructions, implementation essays, freestanding praise, or unrelated context.

## Comment Voice

The global Writing register applies, including its evidence rules and edit pass; this section adds the thread shape. A comment continues the conversation on the author's work, so open with the finding itself, anchored on the symbol or `file:line` it concerns; open with what the change gets right only when that credit carries the point ("The blocking wait makes sense here. I don't want to put the per-request polling back on the runner path."). Name what you verified and what remains unchecked: "I couldn't find a production caller using the direct form, but `--processor` is still an extension point."

A confidently raised issue names the failure plainly with its concrete consequence, makes one ask, and says why that remedy closes the specific failure path, in whatever order and proportion the content wants. Grade the ask to severity: a declinable question by default ("Could we…?"), "Please" plus an imperative only for a genuine blocker, "Let's" for obvious cleanup, and first-person conviction ("I'd drop the count") when confident but not blocking. One shape among many:

> `numRows: null` means "unknown", but `?? 0` persists it as "empty". Could we leave `size` unset in that case and only construct a `BigInt` for an actual count? The schema already gives us an unknown state; preserving it here avoids handing downstream code a confidently wrong zero.

Say plainly what kind of change the ask is and whether behavior visibly changes. Label a non-blocking aside as one ("Nit: `onClick` is typed as `() => void`; `if (onClick)` is enough."). A fragment that reads as speech is fine ("`retry: false` here?"). The one heading a comment earns is a finding title naming the acceptable outcome ("Keep direct processor calls cancellable, or document the exception"), optionally severity-tagged (**[P2]**); everything else stays paragraphs.

In a comment, evidence takes this shape: what the diff establishes is a plain declarative on its `file:line`; a test or handler you did not run on this head takes a modal or a condition ("this should fail once the fixture exceeds one page"), and a check you did run names what you ran. A small fixture passing says nothing about production volume, so say what the code does and what would expose the failure rather than asserting a failure you did not observe.

Before posting, run the global edit pass over the batch as one piece: comments on the same PR must not share an opening construction, a closing move, or a length profile; strike rider tails ("Also, …"), restatements of the author's own diff, and "I noticed"; recheck every `file:line` and every claimed outcome against the current head.

A review summary gives the verdict, the blocking findings, and residual gaps; the inline comments are already visible. A re-review verdict opens with what the new head resolved, then the remainder. When reversing a posted position, say so and give the reason.

Separate review confidence from merge readiness. A clean review does not prove the PR is mergeable.

If actuation is not authorized, provide findings, draft comments, ledger summary, verification run or skipped, and explicit next actions for Ivan.
