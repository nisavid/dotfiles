# Classify The Current Scope

Classify the work by what its result must establish. Use this procedure before
execution and each dispatch, resume, follow-up, or review cycle, and when a
block or refusal raises a routing question.

## Required Judgment

Identify the bounded purpose, affected assets, relevant trust boundaries,
plausible failure effects, and judgment needed for the claimed result. Use
concrete task evidence; a possible security consequence of any software bug is
not enough by itself.

Cybersecurity-related work directly investigates, establishes, or changes a
security property. Cybersecurity-adjacent work has another primary purpose but
requires security judgment to complete it: for example, deciding whether a
test's handling of live credentials prevents disclosure. Both use Daybreak
routing. Security judgment includes assessing adversarial behavior,
unauthorized access or disclosure, authorization boundaries, containment,
vulnerabilities, and cryptographic verification.

Ordinary engineering uses the general matrix when its result requires
correctness, compatibility, reliability, or resource hygiene without such a
security judgment. Keep necessary isolation, ownership checks, and cleanup in
that work. A security-adjacent project, syscall name, sandbox tool, previous
Daybreak assignment, or the word "test" does not determine classification.

| Current scope and claimed result | Classification |
| --- | --- |
| Remove a test-owned disposable directory or reap a cooperative child process with synthetic inputs; failure leaks only test resources. | Ordinary engineering. |
| Observe whether a synthetic guest starts and reports its own metadata on another platform; report only compatibility. | Ordinary engineering; this observation does not certify containment. |
| Decide whether hostile guest code can escape a restriction, read host credentials, expose a debugger, or attach to an unrelated process. | Security judgment. |
| Test credential handling, access restrictions, or signature rejection as evidence that those protections hold. | Security judgment, including when fixtures are synthetic. |
| Copyedit documentation or maintain model-routing examples under settled policy. | Writing under the general matrix. |
| Change what an authorization boundary permits or assess whether a runtime routing control resists bypass. | Security judgment, including when the artifact is prose. |

For mixed work, separate independently useful scopes and state each result's
limits. A compatibility observation can proceed separately from a containment
review when it grants no security acceptance. If one result still requires
both judgments, retain Daybreak routing for that combined scope. A changed
label, shorter prompt, or omitted dependency does not remove a security claim.

If missing facts can change classification, identify the smallest missing fact
and return a scoped clarification through the owning workflow. For example,
before classifying unknown file cleanup, establish ownership, contents, and
whether deletion is relied on to protect a secret. Continue independently
bounded ordinary work where its classification is already supported. Keep an
existing security claim routed until evidence supports a genuinely separate
ordinary scope.

Return the classification, a brief reason tied to the required judgment, and
any missing fact or separated claim. Then apply the selected routing policy
and its authority and capability gates. Classification is not execution
permission or proof of runtime enforcement.

## Reclassify A Follow-Up Review

Before each review dispatch or reuse, establish three facts:

1. State the complete claim the next review must establish and the judgment it
   requires. Include dependencies on which that claim relies.
2. Identify which earlier security findings are resolved and whether changed
   inputs or dependencies invalidate the security evidence still being used.
3. Select the route for that current claim. Record its concrete security
   judgment, or explain why the remaining result is ordinary engineering or
   writing. Reviewer identity, ticket history, and membership in a review loop
   supply no classification evidence.

For example, a Daybreak review resolves an unauthorized-access finding. A
later review limited to wording, synthetic fixture plumbing, or parsing,
deadline, and cleanup correctness uses the general matrix when those changes
leave the security claim and its supporting evidence valid. It does not need
the previous reviewer merely to continue the loop.

If a changed parser, deadline, cleanup path, or other dependency invalidates
that security pass, the next review covers the whole affected security-relevant
scope through Daybreak routing. Checking only the convenient delta cannot
renew the pass. Establish the actual dependency and claim before choosing
either branch; ordinary-sounding filenames do not establish independence.

## Diagnose A Block Or Refusal

Classify ordinary work before trying it; it may then proceed under the general
matrix. Classify security work before execution and apply Daybreak routing
without waiting for a general model to refuse. A refusal is evidence to
diagnose, not an automatic classifier or permission to change routes.

Distinguish the response using the actual error or platform notice:

| Evidence | Next action |
| --- | --- |
| Missing model, capability, entitlement, or capacity. | Verify current capability and use the applicable routing disposition. Preserve the classification and existing fallback restrictions. |
| A platform explicitly supports an authorized specialist handoff for this work. | Verify that supported route, authority, and runnability through the existing gates. A handoff notice alone satisfies none of them. |
| A tool or sandbox denies a filesystem, network, or action permission. | Use the owning workflow's ordinary permission or scope-resolution path. A model change cannot grant that permission. |
| An actual safety refusal prohibits the requested operation. | Stop that operation. Offer a permitted alternative or use the platform's clarification or appeal path when available. |
| An ambiguous response does not identify the cause. | Seek the missing explanation or supported platform guidance before retrying or rerouting the affected operation. Independently permitted work may continue. |

Preserve higher-priority safeguards in every branch. Do not switch models,
accounts, or harnesses, disguise the purpose, or split the same prohibited
operation into subtasks to obtain what a safety refusal withheld. A supported
specialist route serves authorized work within the platform's rules; it is not
a workaround for a prohibition. Existing approval for work or a model does not
override a safety refusal.
