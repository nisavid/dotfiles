# Thermos Synthesis

Use this reference when coordinating nontrivial paired-review output.

## Synthesis Rules

- Keep reviewer findings separate until both passes finish.
- Deduplicate findings that share the same cause, even when one reviewer frames it as risk and the other as maintainability.
- Weight independently confirmed issues more heavily, but do not merge weaker claims into a stronger finding unless the evidence supports it.
- Resolve disagreements with direct source inspection, not by averaging reviewer confidence.
- Do not restate background summaries that are already visible to the user.

## Final Shape

Findings come first. Each finding needs priority, file:line evidence, impact, and a concrete fix direction.

After findings, add only necessary residual risk: missing tests, unreachable context, or uncertainty that could change the verdict.
