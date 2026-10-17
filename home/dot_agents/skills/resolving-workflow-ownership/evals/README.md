# Synthetic comparison corpus for the decision-premise correction

This corpus tests whether an agent checks the rule and observation behind a decision when an uncertain proxy would stop or permit work. It does not test source installation, runtime safeguards, vendor contact, or owner adoption. All rules, systems, identities, and observations in the prompts are fictional. `cases.json` contains prompts only; `expected.json` is the separate answer key. The application set has twelve cases, and discovery has six.

## Case design

A01 and A10 are fictional analogues of the two reported failure shapes: a missing schema label treated as a quota gate, and an available vendor contact treated as a necessary dependency. D01 and D04 test whether those shapes lead to procedure invocation. The remaining cases vary the governing requirement, evidence source, action, and outcome independently. A02 isolates a correct collector with a wrong decision proxy. A03 isolates review of wording against a derived summary. A04–A08 are true gates; A09 keeps a real capacity requirement unknown after removing the invented bucket rule. A11 makes vendor action concrete while preserving submission authority. A12 is a no-op **application** of the skill. D03 and D06 are negative **discovery** controls, so they cannot be scored as no-op application.

## Comparison arms

Use the same frozen task prompts and supported context for each arm, with independent runs and no answer-key access during generation:

1. **Baseline:** the frozen `resolving-workflow-ownership` procedure, with no premise correction.
2. **Corrected:** the maintained procedure with its premise correction. Freeze its bytes and governing dependencies before evaluation.
3. **Ablation:** the same corrected procedure with only the source-and-observation premise check removed, retaining its existing ownership and action rules. This tests whether that check earns its added effort. If the final correction's structure makes this removal incoherent, use a shorter explicit reminder to check the governing rule as the simpler alternative and record the substitution before testing.

Run discovery and application separately. Supply each application prompt with the assigned arm's skill and an instruction to apply it. Supply each discovery prompt with available skill descriptions, then observe invocation before any application answer. Do not interpret a negative discovery result as an application failure, or A12 as a discovery result. Keep case ordering and randomization recorded, and do not let one run see another run's answer or the answer key.

## Scoring and effort record

For each run, record arm, case ID, candidate digest, relevant evidence-dependency digest or version, model, context supplied, invocation decision where applicable, final decision, premise explanation, attempted checks, tool failures, requests to the operator, external actions proposed or attempted, agent effort, and available token or context telemetry. Record telemetry as unknown when unavailable; do not impute a number. Grade against `expected.json`: incorrect blocks, incorrect permission to proceed, unresolved outcomes, review-scope errors, and unsupported or missed escalation. Count both successful and failed attempts in effort; keep operator questions distinct from operator actions. Preserve an unresolved result when the case does not establish a required fact. A source check that is merely suggested, rather than performed in the prompt or observed run, cannot be scored as a verified pass.

Report per-case results and aggregated counts without treating these synthetic cases as a population estimate. Compare correctness and effort across all arms, including routine and valid-gate controls. Do not set a numeric adoption threshold from this corpus. The maintained-procedure owner decides the adoption threshold and accepts any claim of benefit. A changed candidate or material evidence dependency requires new affected runs and review before carrying a result forward. The evaluation coordinator owns execution, scoring, independent review, and any downstream invocation claim.
