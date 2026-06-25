---
name: thermo-nuclear-code-quality-review
description: Strict maintainability audit for branch/PR changes. Use when the user asks for thermo-nuclear code quality, deep code-quality audit, harsh maintainability review, code-judo, file-size, spaghetti, abstraction, or boundary/type-contract review.
---

# Thermo Nuclear Code Quality Review

Run an ambitious maintainability audit. Look for code-judo moves: behavior-preserving restructures that delete complexity.

## Workflow

1. Start from the diff, then inspect surrounding source for ownership, boundaries, and existing helpers.
2. Read `references/code-quality-rubric.md`.
3. Map each meaningful changed concept to its canonical layer or call out why it is misplaced.
4. Prefer findings that simplify the model, delete branches, or remove indirection over local polish.
5. Skip cosmetic nits when structural issues exist.

## Output

Prioritize structural regressions, missed code-judo simplifications, spaghetti growth, boundary/type problems, file-size pressure, and maintainability issues.

Each finding needs file:line evidence, the maintainability risk, and a concrete simpler direction. If no actionable finding meets that bar, say so directly and name residual uncertainty.
