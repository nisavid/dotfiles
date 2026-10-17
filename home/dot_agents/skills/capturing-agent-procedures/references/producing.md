# Produce And Review A Procedure

Read this for new equipment or a useful correction to existing equipment.

## Capture

Add capture to the producer's acceptance criteria before deepening the work, or when the reusable behavior first becomes evident. Use `writing-for-agents` for instructions and skills; read its `SKILL-MECHANICS.md` when writing a skill. Resolve referenced skills through the current harness.

Capture the entry conditions, supported inputs, ordered procedure, decision branches, relevant references or helpers, and observable completion criteria. Keep specimen decisions and historical evidence in their owning artifacts, linking them where useful. Incorporate salient corrections from execution and review. Update authorized active guidance that contradicts a settled correction while preserving historical evidence.

For example, a repo's export task can extend its existing diagram skill with the new export branch and acceptance checks. The accepted diagram stays in the design artifact; later diagram tasks invoke the skill and depend on the producer's validated revision.

## Evaluate And Improve

Use the standing review policy's supported review and adjudication route for the candidate equipment. Keep review, evaluation, revision, and adjudication as explicit operations; do not infer one from another.

1. Evaluate with `plugin-eval:evaluate-skill` when that route is available; review the instructions and their relevant references/helpers. Record findings and their valid, fixed, rejected-with-evidence, or decision-blocked disposition through the owning workflow.
2. Address valid findings through `plugin-eval:improve-skill`, using the installed `skill-creator` equivalent when supported. Reevaluate affected behavior after improvements. Every selected review focus and evaluation requires current evidence on the final candidate.
3. Derive tests from the candidate procedure's entry conditions, supported inputs, decision branches, and completion criteria. Test discovery separately: include requests that should invoke the procedure and nearby requests that should not. For application, test observable success, failure, and no-op results. A no-op application still invokes the procedure, so it cannot substitute for negative discovery. Static analysis alone does not establish these behaviors.

Keep decisions and stopping rules with the applicable workflow and operator. Unavailable evaluation controls remain missing evidence through that owner; use another evaluation route only when authorized, with its actual evidence and limits. Any candidate or relevant dependency change invalidates affected evidence; every selected focus needs a clean latest pass on the final revision.

For instruction-only changes, review the instruction artifact and exercise its owning skill or route. Pass only valid skill packages to skill evaluators. When reviewing instructions that themselves describe review loops, keep the review of that artifact separate from executing its described loop; do not recursively invoke the procedure being evaluated. Report unavailable evaluation capabilities as missing evidence through the owning workflow.
