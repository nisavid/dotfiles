# Code Quality Rubric

Use this rubric after the initial diff pass.

## Primary Questions

- Is there a code-judo move that makes this dramatically simpler?
- Can the model change so branches, modes, or helper layers disappear?
- Is the logic in the canonical file, package, service, or module?
- Did the diff make a cohesive module more coupled, stateful, or harder to scan?
- Is an abstraction earning its keep, or is it indirection?
- Did casts, optionality, fallback behavior, or ad-hoc object shapes obscure an invariant?
- Did the change duplicate an existing helper or bypass a canonical utility?

## Presumptive Blockers

- Preserved incidental complexity when a simpler model is visible.
- A file crossing from under 1000 lines to over 1000 lines without a strong structural reason.
- Ad-hoc branches, flags, nullable modes, or scattered special cases in an already busy flow.
- Feature-specific logic leaking into shared paths.
- Thin wrappers, cast-heavy contracts, or generic magic that hide simple structure.
- Related updates that are less atomic or more sequential than the concept requires.

## Preferred Remedies

- Delete a layer of indirection rather than polish it.
- Reframe state so conditionals disappear.
- Move logic to the owner that already owns the concept.
- Reuse canonical helpers instead of adding near-duplicates.
- Split large files into focused modules.
- Make type boundaries explicit so control flow gets simpler.
