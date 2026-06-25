---
name: thermos
description: Run paired thermo-nuclear review passes and synthesize findings. Use when the user asks for thermos, double thermo review, or combined risk and maintainability branch review.
---

# Thermos

Run two independent review passes, then synthesize one findings-first verdict.

## Workflow

1. Define the review scope. Complete this when the base, head, and included paths are explicit.
2. Gather the diff and changed-file context needed for both reviewers to evaluate without guessing.
3. Run the passes independently:
   - Use `thermo-nuclear-review` for correctness, security, breaking behavior, devex regressions, feature-gate leaks, and branch-audit risk.
   - Use `thermo-nuclear-code-quality-review` for structure, maintainability, code-judo opportunities, file-size pressure, abstractions, boundaries, and codebase health.
4. Prefer parallel subagents when available and worth the overhead; otherwise run sequentially while keeping findings separate until synthesis.
5. For nontrivial overlap, disagreement, or long reviewer output, read `references/synthesis.md` before writing the final verdict.

## Output

Lead with deduplicated findings ordered by severity. Include file:line evidence, impact, and the smallest actionable remedy. If no high-conviction findings survive, say so directly and name residual test or review gaps.
