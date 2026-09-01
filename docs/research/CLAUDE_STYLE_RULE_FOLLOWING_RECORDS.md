# Claude Style-Rule Following: Run Records

Sanitized records behind `CLAUDE_STYLE_RULE_FOLLOWING.md`. Generated from the
session's workflow artifacts on 2026-09-01. Executor: `claude-opus-5`, high
reasoning effort, one generation per (scenario, condition). Judges:
`claude-fable-5`, two blinded passes per scenario (a tell-hunt lens and a
colleague-read lens); draft labels were rotated per scenario so judges could
not infer condition order. Scores are 0-10. Aggregates in the research note
average across judge passes per condition. Sample sizes are as shown here; no
other runs occurred. The appendices reproduce the tested rule and exemplar text
verbatim, including a known tension: the rules forbid topic labels while the
calibration exemplars open a nit with `Nit:`, which confounds the
exemplar-enriched conditions and is left uncorrected because the appendices are
evidence, not policy.

## Round 1 (2026-08-31)

Conditions: `control` (task only), `rules` (task + rules block, appendix A),
`rules_ex` (task + rules block + calibration exemplars, appendix B).
Scenarios: `batch` (review body + two inline comments), `reply` (author reply
in a review thread), `parking` (status comment on own draft PR).

Blinding key: {"batch": {"X": "control", "Y": "rules", "Z": "rules_ex"}, "reply": {"X": "rules", "Y": "rules_ex", "Z": "control"}, "parking": {"X": "rules_ex", "Y": "control", "Z": "rules"}}

| Scenario | Lens | Draft | Condition | AI-tell freedom | Register | Fidelity |
|---|---|---|---|---|---|---|
| batch | tells | X | control | 7 | 9 | 9 |
| batch | tells | Y | rules | 6.5 | 9 | 7 |
| batch | tells | Z | rules_ex | 4.5 | 7 | 8 |
| batch | colleague | X | control | 6 | 7 | 9.5 |
| batch | colleague | Y | rules | 7.5 | 9 | 6.5 |
| batch | colleague | Z | rules_ex | 6.5 | 7.5 | 8 |
| reply | tells | X | rules | 8 | 9 | 10 |
| reply | tells | Y | rules_ex | 9 | 9 | 9 |
| reply | tells | Z | control | 5 | 6 | 9 |
| reply | colleague | X | rules | 9 | 9 | 9 |
| reply | colleague | Y | rules_ex | 9 | 9 | 8 |
| reply | colleague | Z | control | 6 | 6 | 8 |
| parking | tells | X | rules_ex | 7.5 | 9 | 9 |
| parking | tells | Y | control | 6.5 | 8 | 9.5 |
| parking | tells | Z | rules | 8 | 9 | 7 |
| parking | colleague | X | rules_ex | 8.5 | 8.5 | 9.5 |
| parking | colleague | Z | rules | 8.5 | 9 | 7 |
| parking | colleague | Y | control | 6.5 | 6 | 9 |

## Round 2 (2026-08-31)

Conditions: `rules_v2` (revised rules, appendix C), `rules_v2_ex` (revised
rules + exemplars with anti-mimicry caveat, appendix D). Scenarios: the two
weaker round-1 scenarios (`batch`, `parking`), regenerated fresh.

Blinding key: {"batch": {"X": "rules_v2", "Y": "rules_v2_ex"}, "parking": {"X": "rules_v2_ex", "Y": "rules_v2"}}

| Scenario | Lens | Draft | Condition | AI-tell freedom | Register | Fidelity |
|---|---|---|---|---|---|---|
| batch | tells | X | rules_v2 | 9 | 9 | 9 |
| batch | tells | Y | rules_v2_ex | 5 | 7 | 6 |
| batch | colleague | X | rules_v2 | 8 | 8 | 9 |
| batch | colleague | Y | rules_v2_ex | 6 | 7 | 7 |
| parking | tells | X | rules_v2_ex | 8 | 9 | 9 |
| parking | tells | Y | rules_v2 | 6 | 8 | 8 |
| parking | colleague | X | rules_v2_ex | 7 | 8 | 9 |
| parking | colleague | Y | rules_v2 | 5 | 6 | 8 |

## Round 1 drafts and fact briefs

### Scenario `batch`

Fact brief:

```text
Verified facts, all confirmed by you the reviewer (do not invent beyond these):
- The PR adds a Redis cache in front of the feature-flag loader (src/flags/loader.ts). Cache entries use a 300-second TTL.
- The flags service already publishes invalidation events on the 'flags.changed' channel; the new cache does not subscribe to them. You verified this by reading the subscriber registry: nothing subscribes.
- Consequence you verified: after an operator flips a kill switch, pods keep serving the stale flag for up to 5 minutes. The PR description says "no behavior change".
- loader.test.ts line 88 asserts the exact private cache-key string ("flags:v2:" + tenant + ":" + name). The public behavior (stale-after-TTL, hit/miss counts) is untested.
- Line 12 of loader.ts imports 'chalk'; nothing in the file uses it.
- The cache itself is a real win: p50 flag lookup drops from 11ms to 0.3ms per the PR's own benchmark, which you reproduced.
```

#### Draft X (condition: `control`)

```markdown
BODY

The cache is a real win — I reproduced the benchmark and p50 flag lookup does drop from 11ms to 0.3ms. I want this in.

One thing blocks it: nothing subscribes to `flags.changed`. I read through the subscriber registry and the new cache isn't there, so the 300-second TTL is the only thing that ever removes an entry. After an operator flips a kill switch, pods keep serving the old value for up to five minutes. That also makes "no behavior change" in the description inaccurate — how fast a kill switch reaches a pod is exactly what changes here, and it's the property people rely on during an incident.

Two smaller items: the new test pins the private cache-key string rather than the behavior anyone depends on, and line 12 imports `chalk` with nothing in the file using it.

---

INLINE src/flags/loader.ts:41

This 300-second TTL is currently the only path that expires an entry. The flags service already publishes invalidation on `flags.changed`, and no subscriber picks it up — I checked the subscriber registry and neither the cache nor the loader is registered.

Can you subscribe here and drop the key on the event? Then the TTL becomes a backstop for a missed message instead of the primary invalidation mechanism, and 300s is a perfectly good number for that role.

---

INLINE src/flags/loader.test.ts:88

This asserts the private key format, so renaming the prefix to `v3` or changing the separator fails the test even though nothing observable changed. The behavior worth locking down isn't covered: a repeat lookup serves from cache, a lookup after the TTL goes back to the store, and — once invalidation lands — a `flags.changed` event drops the entry.

I'd trade this assertion for those three. If you want the key shape guarded, one focused test on the key builder states that intent without coupling every loader test to it.
```

#### Draft Y (condition: `rules`)

```markdown
BODY

Nothing in the subscriber registry listens on `flags.changed`, so once an operator flips a kill switch, pods keep serving the old value for the rest of the 300-second TTL. That's up to five minutes with a flag off in the console and on in the fleet, and the description says no behavior change. Please hook the cache up to the invalidation channel before this merges.

The cache itself I want in — I reran the benchmark and p50 lookup really does go from 11ms to 0.3ms.

`chalk` on line 12 is imported and never used; let's drop it.

---

INLINE src/flags/loader.ts:41

`flags.changed` already carries exactly the event this cache needs, and nothing subscribes to it today, so the 300-second TTL is the only thing that can clear a stale entry. Could we subscribe here and delete the affected key when an event lands? Then the TTL is a backstop for dropped messages instead of the only path back to truth, and a kill switch takes effect when the operator flips it.

---

INLINE src/flags/loader.test.ts:88

This asserts the literal cache key, `"flags:v2:" + tenant + ":" + name`. Rename the prefix and the test fails while nothing observable has changed; meanwhile the parts a caller can feel — a value staying stale until the TTL lapses, hit and miss counts — have no coverage at all. I'd trade this assertion for a fake-clock test: read a flag, change it underneath, assert the old value before expiry and the new one after. Written that way it fails on this branch, which is the point.
```

#### Draft Z (condition: `rules_ex`)

```markdown
BODY

The cache delivers: I reran your benchmark and got the same p50 drop from 11ms to 0.3ms, which is a big deal on a path this hot. Requesting changes on one thing before it merges.

With a 300-second TTL and no subscription to `flags.changed`, a kill switch flip takes up to five minutes to reach pods. That's a real behavior change from today's read-through path, so the "no behavior change" line in the description needs to go either way. Details in the inline comment on the loader.

Also, `chalk` on line 12 is unused. Let's drop the import.

---

INLINE src/flags/loader.ts:41

TTL expiry is the only way a stale entry leaves this cache. The flags service already publishes on `flags.changed`, but I checked the subscriber registry and nothing is listening, so an operator who flips a kill switch waits up to 300 seconds before pods stop serving the old value. That's the case where flags matter most.

Please subscribe to `flags.changed` and delete the affected key on receipt. The publisher side already exists, so this is a listener plus a `DEL`, and it turns the TTL back into a backstop instead of the propagation floor.

---

INLINE src/flags/loader.test.ts:88

This asserts the literal `"flags:v2:" + tenant + ":" + name`, which locks in a private detail. Rename the prefix or add a shard segment and the test fails even though nothing observable changed, while the behavior callers depend on has no coverage: that a value goes stale after the TTL, and that a second lookup hits instead of missing.

Could we drop the key assertion and cover those two instead? Then the test fails when the cache misbehaves rather than when we rename something.
```

### Scenario `reply`

Fact brief:

```text
Verified facts (do not invent beyond these):
- The provider webhook exists and fires on first settlement attempt, but you tested retried settlements in the sandbox and the webhook does not fire on retries; their docs confirm retries are webhook-silent.
- Roughly 2% of settlements in the last 90 days were retries (you queried the ledger).
- Your decision: subscribe to the webhook for the primary path, keep a poll as reconciliation but drop its frequency from 30s to 10 minutes, and you already pushed this in commit 8c41f02.
- The reviewer's suggestion genuinely improves the primary path latency; the original 30s poll was your own earlier design.
```

#### Draft X (condition: `rules`)

```markdown
Switched the primary path to the webhook in 8c41f02 — beats waiting up to 30s for the next tick.

I kept a poll, though, because the webhook only fires on the first settlement attempt. I ran retries through their sandbox and got no event, and their docs say retries are webhook-silent. Retries were about 2% of settlements over the last 90 days, so with the loop gone those would never get marked settled. It's now a 10-minute reconciliation sweep rather than a 30s primary path. Does that split work for you, or would you rather we chase the provider about emitting retry events?
```

#### Draft Y (condition: `rules_ex`)

```markdown
Webhook subscription is in as of 8c41f02, so the primary path no longer waits on a tick. The loop can't go away entirely though: I ran retried settlements through the provider sandbox and no webhook fires on a retry, and their docs confirm retries are webhook-silent. Retries were about 2% of settlements over the last 90 days, and without the poll those never get confirmed.

So the poll stays as reconciliation only, dropped from 30s to 10 minutes. If you'd rather stretch that further now that it's not the primary path, I'm fine going to an hour.
```

#### Draft Z (condition: `control`)

```markdown
You're right about the primary path — the webhook gets settlement confirmation from up-to-30s down to near-immediate, so I've subscribed to it in 8c41f02.

I can't delete the loop entirely, though. The webhook only fires on the first settlement attempt. I ran retried settlements through the sandbox and got no event, and the provider's docs confirm retries are webhook-silent. Retries were about 2% of settlements over the last 90 days, so those would just go unconfirmed.

So the loop stays, but as reconciliation rather than the primary path, and at 10 minutes instead of 30 seconds. The 30s cadence was my own earlier design from when polling was the only path; it no longer has to carry the latency requirement. If the provider ever emits retry events, the loop can go away completely.
```

### Scenario `parking`

Fact brief:

```text
Verified facts (do not invent beyond these):
- PR #88 mixes two things: a bump of the protobuf toolchain (needed) and a refactor of the codegen config layout (your experiment).
- You have decided the refactor approach is wrong in its current form; you prototyped it quickly and no longer stand behind the layout.
- The toolchain bump has meanwhile been superseded: PR #91 (merged yesterday) already bumped protobuf further than this branch does.
- Your plan: keep the draft open as a reference, split the config refactor into a fresh draft when you redesign it, and let #91 stand for the bump.
```

#### Draft X (condition: `rules_ex`)

```markdown
Nothing here needs review. Two things are tangled in this branch, and both have moved on.

The protobuf bump is superseded — #91 merged yesterday and goes further than this branch does. That's the one to build on.

The codegen config layout is my experiment, and I don't stand behind it in this shape. I prototyped it fast to see how it would feel, and the layout it landed on isn't right. When I redesign it, it goes in a fresh draft rather than more commits here.

I'm leaving this open as a reference for the layout question in the meantime. If something pointed you at this PR, #91 is the answer for the toolchain, and the refactor isn't a proposal yet.
```

#### Draft Y (condition: `control`)

```markdown
Status for anyone who wanders in: don't review this, and don't wait on it.

Two unrelated things are tangled together here — a protobuf toolchain bump and my experiment with the codegen config layout. The bump no longer matters: #91 merged yesterday and moves protobuf further than this branch does, so #91 is the one to build on. The config refactor I put together fast, and I don't stand behind the layout anymore. It's wrong in this form, and I'd rather redesign it than keep patching it here.

So this draft stays open purely as a reference for the shape I tried. When I've reworked the layout, it lands as a fresh draft rather than more commits on this one. If you came looking for newer protobuf, you already have it.
```

#### Draft Z (condition: `rules`)

```markdown
Two things are tangled in this branch: the protobuf toolchain bump and my rewrite of the codegen config layout. Neither is landing as-is.

The bump is moot now. #91 merged yesterday and takes protobuf further than this branch does, so let that one stand.

The config layout I no longer stand behind. I prototyped it fast to see what the shape felt like, and the shape is wrong. Redesigning it here would mean rewriting most of the diff, so I'd rather start clean.

Leaving this open as a reference for the parts I want to keep in mind. When I have a layout I believe in, it comes back as a fresh draft. Nothing here needs review.
```


## Round 2 drafts and fact briefs

### Scenario `batch`

Fact brief:

```text
Verified facts, all confirmed by you the reviewer (do not invent beyond these):
- The PR adds a Redis cache in front of the feature-flag loader (src/flags/loader.ts). Cache entries use a 300-second TTL.
- The flags service already publishes invalidation events on the 'flags.changed' channel; the new cache does not subscribe to them. You verified this by reading the subscriber registry: nothing subscribes.
- Consequence you verified: after an operator flips a kill switch, pods keep serving the stale flag for up to 5 minutes. The PR description says "no behavior change".
- loader.test.ts line 88 asserts the exact private cache-key string ("flags:v2:" + tenant + ":" + name). The public behavior (stale-after-TTL, hit/miss counts) is untested.
- Line 12 of loader.ts imports 'chalk'; nothing in the file uses it.
- The cache itself is a real win: p50 flag lookup drops from 11ms to 0.3ms per the PR's own benchmark, which you reproduced.
```

#### Draft X (condition: `rules_v2`)

```markdown
BODY

Nothing subscribes to `flags.changed`. I went through the subscriber registry to be sure, and combined with the 300-second TTL that means an operator flipping a kill switch keeps getting the old value out of every pod for up to five minutes. The description says "no behavior change"; this is the exception. Please add the subscription before this merges.

The cache itself I want. I reran your benchmark and got the same p50 drop, 11ms to 0.3ms.

`chalk` is imported at line 12 and nothing in the file uses it. Let's drop it.

---

INLINE src/flags/loader.ts:41

The 300-second TTL is the only thing that evicts an entry here, so that's the full width of the kill-switch delay. Could the cache subscribe to `flags.changed` and delete the affected key as events arrive, leaving the TTL as the backstop for messages we miss? Then a flip propagates on the next lookup instead of whenever the entry happens to age out.

---

INLINE src/flags/loader.test.ts:88

Asserting the exact key string pins a private detail: rename the prefix in a future cache migration and this would go red with nothing user-visible broken. The behavior a reader actually wants guaranteed isn't here yet, namely that a repeat lookup hits the cache and that a lookup past the TTL re-reads the source. I'd trade this assertion for those two cases.
```

#### Draft Y (condition: `rules_v2_ex`)

```markdown
BODY

Nothing subscribes to `flags.changed`, so the new Redis layer only drops entries when the 300-second TTL lapses. After an operator flips a kill switch, pods keep serving the old value for up to five minutes, and the PR description says no behavior change. I read the subscriber registry to confirm the channel has no listeners.

The cache itself I want: I reran your benchmark and got the same p50 move from 11ms to 0.3ms. Please have the loader subscribe to `flags.changed` and delete the affected key on each event, so a flip takes effect on the next lookup rather than whenever the window happens to close.

---

INLINE src/flags/loader.ts:41

The 300-second TTL on this write is the only thing that evicts an entry, so a revoked flag can stay live for the full window no matter what the flags service publishes. Could we subscribe to `flags.changed` and delete the key for the tenant and flag named in the event, leaving the TTL as a backstop for events we miss?

`chalk` on line 12 isn't used anywhere in the file.

---

INLINE src/flags/loader.test.ts:88

This asserts the literal key `flags:v2:<tenant>:<name>`, which pins a private format: renaming the prefix breaks the test without breaking anything a caller can observe. Nothing covers the behavior that would have caught the invalidation gap, either, meaning a stale read once the TTL lapses and hit versus miss on a repeated lookup. Could we swap this for a read-through test that asserts a single backend call, plus one that advances the clock past the TTL?
```

### Scenario `parking`

Fact brief:

```text
Verified facts (do not invent beyond these):
- PR #88 mixes two things: a bump of the protobuf toolchain (needed) and a refactor of the codegen config layout (your experiment).
- You have decided the refactor approach is wrong in its current form; you prototyped it quickly and no longer stand behind the layout.
- The toolchain bump has meanwhile been superseded: PR #91 (merged yesterday) already bumped protobuf further than this branch does.
- Your plan: keep the draft open as a reference, split the config refactor into a fresh draft when you redesign it, and let #91 stand for the bump.
```

#### Draft X (condition: `rules_v2_ex`)

```markdown
Nothing here needs review. The protobuf bump is already covered by #91, which merged yesterday and goes further than this branch does, so that half is moot. The config layout refactor is the part I still want, just not in this shape: I prototyped the layout fast and I don't stand behind it.

I'm keeping the draft open as a reference for the redesign, and the refactor will come back as a fresh draft once the layout is something I'd defend. If you landed here looking for the protobuf change, #91 is the one.
```

#### Draft Y (condition: `rules_v2`)

```markdown
Two unrelated things are riding in this branch: the protobuf toolchain bump and my rework of the codegen config layout. Neither one is going in from here.

#91 merged yesterday and bumps protobuf past where this branch takes it, so #91 stands for the bump.

The config layout is my own experiment and I no longer stand behind it. I prototyped it fast to see how it would feel in use, and the shape it landed in isn't the right one. When I redesign it I'll open a fresh draft rather than keep pushing on this one.

So: staying a draft, staying open as a reference for the layout attempt. Don't wait on it for anything.
```


## Appendix A: round-1 rules block

```markdown
## Review-comment writing rules

Open with the finding itself as a plain declarative, anchored on a backticked symbol or concrete mechanism. No scene-setting, no topic labels ("On tags:"), no headings, no "I noticed".

Give each comment exactly one ask, graded to severity: a declinable question by default ("Could we…?", "should we…?"); "Please" plus an imperative only for a genuine blocker; "Let's" for obvious cleanup; first-person conviction ("I'd drop the count") when confident but not blocking. Say why the remedy closes the specific failure path.

Write only what the evidence shows. "The config record hasn't changed since June 2" is an observation; "the update silently failed" is a story. If you didn't verify the story, write the observation. A detail earns its place only if it changes what the reader does next; cut inventories and enumerations that just show your work.

Before sending, run these checks and fix what they catch:
- Em dashes: unspaced, at most a couple per message, and only where a dash genuinely beats a colon, parentheses, semicolon, or a new sentence.
- Strike on sight: "worth noting", "worth also", "It's important to", "credit where due", "That said", arrow chains, aphorism or epigram phrasing in opening and closing slots, any coinage you wouldn't say aloud to a colleague.
- Across a batch of comments: if two share an opening shape, a closing move, or a length profile, rewrite one from its own content. Watch for the tacked-on rider tail ("Also, …" / "Worth also…" closing several comments).
- Reread each comment as its recipient. Anything that reads as a machine's note-to-self (mechanical parallelism, obsessive precision, restating what the reader already knows) gets rewritten as speech.

Fragments that read as speech are welcome. Contractions throughout. "We" for the codebase, "I" for judgment. Credit real strengths only when the credit is load-bearing for the point, never as freestanding praise. When agreeing, say little and act; never restate the other person's comment back at them.
```

## Appendix B: round-1 calibration exemplars

```markdown
## Calibration — match this register, not these words

Blocking finding:
> This now renders raw enum values like \`LANGUAGE_MODEL\`. Please keep the human-readable formatting or use an explicit label map.

Finding with mechanism and a declinable ask:
> \`numRows: null\` means "unknown", but \`?? 0\` persists it as an actual zero. Could we leave \`size\` unset in that case and only construct a \`BigInt\` for an actual count? The schema already gives us an unknown state; preserving it avoids handing downstream code a confidently wrong zero.

Nit:
> Nit: can we drop \`flex-1\` here? This row is not inside a flex parent, so it has no effect.

Confident middle path:
> Old harness. 82 is the full matrix of the build baked into \`inference-vllm-smoke:0.1.56\`, which is what the staging job was still running; the current harness gives \`pass=127\` on a clean run. Any pinned count goes stale when the matrix moves anyway. I'd just say to look for \`fail=0\`.
```

## Appendix C: round-2 rules block (v2)

```markdown
## Review-comment writing rules

Open with the finding itself as a plain declarative, anchored on a backticked symbol or concrete mechanism. No scene-setting, no topic labels ("On tags:", "Status:"), no headings, no "I noticed".

Give each comment exactly one ask, graded to severity: a declinable question by default ("Could we…?", "should we…?"); "Please" plus an imperative only for a genuine blocker; "Let's" for obvious cleanup; first-person conviction ("I'd drop the count") when confident but not blocking. Say why the remedy closes the specific failure path.

Evidence is a hard constraint, and style pressure never licenses invention:
- Never assert what a test, command, or system does unless your brief says you ran it. Write "this should fail once the cache is wired up", not "this fails".
- Never commit yourself to a position, threshold, offer, or concession that is not in your brief.
- Write the observation, not the story: "the config record hasn't changed since June 2", not "the update silently failed".
- A detail earns its place only if it changes what the reader does next; cut inventories that show your work.

After drafting, EDIT before sending — these are actions, not preferences:
1. Scan the text for "—" and for " - " used as a dash. Replace every one with a colon, parentheses, semicolon, or a new sentence unless a dash is genuinely the best structure; at most one or two survivors per message, written unspaced (word—word).
2. Reread the LAST sentence of each piece. If it lands like a mic-drop or a tidy recap ("That's the case where flags matter most.", "The loop earns its keep."), delete it or replace it with the plain point.
3. Strike on sight: "worth noting", "worth also", "It's important to", "credit where due", "That said", arrow chains, any coinage you wouldn't say aloud to a colleague.
4. Across a batch: if two pieces share an opening shape, a closing move, or a length profile, rewrite one from its own content. Watch for the rider tail ("Also, …" closing several pieces).
5. Reread each piece as its recipient. Anything that reads as a machine's note-to-self (mechanical parallelism, obsessive precision, restating what the reader already knows) gets rewritten as speech.

Fragments that read as speech are welcome. Contractions throughout. "We" for the codebase, "I" for judgment. Credit real strengths only when the credit is load-bearing for the point; when agreeing, say little and act; never restate the other person's comment back at them.
```

## Appendix D: round-2 calibration exemplars (v2)

```markdown
## Calibration

Match the register of these samples, not their compression. They are plain speech that happens to be short — do not manufacture aphorisms, punchlines, or crafted closers to imitate them.

Blocking finding:
> This now renders raw enum values like \`LANGUAGE_MODEL\`. Please keep the human-readable formatting or use an explicit label map.

Finding with mechanism and a declinable ask:
> \`numRows: null\` means "unknown", but \`?? 0\` persists it as an actual zero. Could we leave \`size\` unset in that case and only construct a \`BigInt\` for an actual count? The schema already gives us an unknown state; preserving it avoids handing downstream code a confidently wrong zero.

Nit:
> Nit: can we drop \`flex-1\` here? This row is not inside a flex parent, so it has no effect.

Confident middle path:
> Old harness. 82 is the full matrix of the build baked into \`inference-vllm-smoke:0.1.56\`, which is what the staging job was still running; the current harness gives \`pass=127\` on a clean run. Any pinned count goes stale when the matrix moves anyway. I'd just say to look for \`fail=0\`.
```
