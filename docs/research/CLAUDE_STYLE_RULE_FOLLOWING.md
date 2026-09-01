# Claude Style-Rule Following: Preferences vs Edit Actions

Research note. Observed 2026-08-31 on `claude-opus-5` at high reasoning effort,
drafting GitHub PR review comments in two rounds of blind A/B tests (three
fresh scenarios; drafts scored blind by Claude Fable 5 judge panels on
AI-writing tells, register match, and factual fidelity). This is a dev-side
note for instruction authors; it deploys nowhere. Scale: nine drafts over six
blind judge passes in round one, four drafts over four passes in round two;
scores are 0-10, averaged per condition across judge passes. The run records
are session-local, so read every number here as a small-sample observation,
not a benchmark.

## Observation

Style constraints stated as rules or preferences ("em dashes are unspaced")
were unreliably applied at generation time: spaced em dashes appeared in every
test condition, including the conditions whose instructions stated the rule
explicitly. The same constraints rephrased as mandatory post-draft edit
actions ("after drafting, scan the text for '—' and judge each occurrence")
were applied consistently: zero em-dash defects across all drafts in the
follow-up round.

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

Under strong style rules, `claude-opus-5` invented details it was not given:
unverified test outcomes stated as fact, motives, and self-committed
concessions. Blind-judged fidelity dropped roughly 9.0 → 7.75 (0–10) until an
explicit evidence guard was added ("never assert a test outcome you didn't
run; write 'should fail', not 'fails'"). The primary mitigation is grounding,
not guards: supply the load-bearing detail and leave the rest legitimately
discoverable with tools. An under-grounded drafting task reads to the model as
a rhetoric exercise, and it supplies rhetorical (invented) observations to
match. Guards remain a useful backstop.

## Implication for authoring Claude-facing writing policy

Pair each style preference with a nuanced post-draft edit action; keep
evidence-grounding requirements alongside style rules; and for batches that
matter, prefer one adversarial review pass over a finished draft (tell hunt
plus fact-fidelity check) to piling on more generation-time rules; residual
tells leaked in roughly half of generations under every rule set tested.
