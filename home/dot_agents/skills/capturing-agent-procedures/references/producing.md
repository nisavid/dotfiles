# Produce And Review A Procedure

Read this for new equipment or a useful correction to existing equipment.

## Capture

Add capture to the producer's acceptance criteria before deepening the work, or when the reusable behavior first becomes evident. Use `writing-for-agents` for instructions and skills; read its `SKILL-MECHANICS.md` when writing a skill. Resolve referenced skills through the current harness.

Capture the entry conditions, supported inputs, ordered procedure, decision branches, relevant references or helpers, and observable completion criteria. Keep specimen decisions and historical evidence in their owning artifacts, linking them where useful. Incorporate salient corrections from execution and review. Update authorized active guidance that contradicts a settled correction while preserving historical evidence.

For example, a repo's export task can extend its existing diagram skill with the new export branch and acceptance checks. The accepted diagram stays in the design artifact; later diagram tasks invoke the skill and depend on the producer's validated revision.

## Evaluate And Improve

Use `ralph-review-until-clean` for one labeled loop on the candidate equipment:

1. Evaluate with `plugin-eval:evaluate-skill`; review the instructions and their relevant references/helpers. Classify findings using Ralph's valid, fixed, rejected-with-evidence, and operator-blocked states.
2. Address valid findings through `plugin-eval:improve-skill`, using the installed `skill-creator` equivalent. Reevaluate with `plugin-eval:evaluate-skill` after improvements. Continue alternating until the latest evaluation of the final candidate is clean.
3. Derive realistic discovery and application tests from the candidate procedure's entry conditions, supported inputs, decision branches, and completion criteria, including relevant failure and no-op paths. Static analysis alone does not establish the procedure's behavior.

Ralph owns escalation checkpoints and stopping rules. Active checkpoints or operator-blocked findings pause the loop for the required decision. Any candidate or relevant dependency change invalidates affected evidence; every selected focus needs a clean latest pass on the final revision.

For instruction-only changes, review the instruction artifact and evaluate/exercise its owning skill or route. Pass only valid skill packages to skill evaluators. When the artifact describes review-loop instructions, apply Ralph's anti-recursion rule to that artifact; do not create a recursive review loop. Report unavailable evaluation capabilities as missing evidence through the owning workflow.
