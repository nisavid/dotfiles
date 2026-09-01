# Claude Style-Rule Following: Preferences vs Edit Actions

Research note. Observed 2026-08-31 on `claude-opus-5` at high reasoning effort,
drafting GitHub PR review comments in two rounds of blinded multi-condition
comparisons (round one: three conditions; round two: two; drafts scored blind
by Claude Fable 5 judge panels on AI-writing tells, register match, and factual
fidelity). This is a dev-side note for instruction authors; it deploys nowhere.
Scale: nine drafts over six blind judge passes in round one, four drafts over
four passes in round two; scores are 0-10, averaged per condition across judge
passes. Sanitized run records (scenarios, rule blocks, all drafts, blinded
per-judge scores) are committed alongside this note as
`CLAUDE_STYLE_RULE_FOLLOWING_RECORDS.md`; the sample is small, so read every
number as an observation, not a benchmark.

## Observation

Style constraints stated as rules or preferences ("em dashes are unspaced")
were unreliably applied at generation time: spaced em dashes appeared in six of
the nine round-one drafts, spanning all three conditions, including the two
whose instructions stated the rule explicitly. The same constraints rephrased
as mandatory post-draft edit actions ("after drafting, scan the text for '—'
and judge each occurrence") were applied consistently: zero em-dash defects
across all drafts in the follow-up round.

GPT-family models do not exhibit this gap nearly as much (operator
observation, not re-tested here). Treat "phrase style constraints as edit
actions" as Claude-targeted authoring guidance, not a universal rule.

## Caveat: edit actions amplify absolutism

An edit action is executed more literally than a preference, so it must carry
the full nuance of the preference it enforces, or it over-applies:

- Correct em-dash treatment depends on the usage. Parenthetical em dashes are
  always unspaced; some bespoke non-parenthetical usages are legitimately
  spaced. The action must be "judge each occurrence's usage, then fix
  accordingly", never a blanket transform.
- Avoid arbitrary numeric criteria ("at most two per message"). They block
  legitimate uses and, applied mechanically, can corrupt unusual content.

## Related: style pressure and hallucination

Under strong style rules, `claude-opus-5` invented details it was not given.
Examples from the committed records: an unverified test outcome stated as fact
("Written that way it fails on this branch, which is the point"; round one,
`rules`, batch scenario; the described test passes), an invented motive ("to
see how it would feel in use"; round two, `rules_v2`, parking scenario), and a
self-committed concession ("I'm fine going to an hour"; round one, `rules_ex`,
reply scenario). Blind-judged fidelity (0-10) averaged 9.0 for round-one
`control` and 7.75 for round-one `rules`. Round two added an explicit evidence
guard ("never assert a test outcome you didn't run; write 'should fail', not
'fails'") together with other rule changes, and `rules_v2` fidelity averaged
8.5; the guard's isolated effect was not measured. The primary mitigation is
grounding, not guards: supply the load-bearing detail and leave the rest
legitimately discoverable with tools. The working hypothesis for the mechanism,
not something these runs measured: an under-grounded drafting task reads to the
model as a rhetoric exercise, so it supplies rhetorical (invented) observations
to match. Guards remain a useful backstop.

## Implication for authoring Claude-facing writing policy

Pair each style preference with a nuanced post-draft edit action; keep
evidence-grounding requirements alongside style rules; and for batches that
matter, prefer one adversarial review pass over a finished draft (tell hunt
plus fact-fidelity check) to piling on more generation-time rules; residual
tells (mic-drop closers, recap tails, rider phrasing) still surfaced under
every rule set tested.
