---
name: applying-diataxis
description: Use when writing, reviewing, or restructuring durable technical or product documentation with Diataxis; when deciding whether content should be a tutorial, how-to guide, reference, or explanation; when docs mix learning paths, task instructions, factual lookup, and conceptual rationale.
---

# Applying Diataxis

Diataxis classifies documentation by the user's immediate need. Use it to give each page one primary job, then split or link material that serves a different job.

This skill is for durable technical or product documentation: docs sites, READMEs, user guides, API docs, package docs, runbooks, docs indexes, and concept pages. It is not the default for PR bodies, issue comments, chat replies, release notes, or ephemeral coordination prose.

## Compass

Classify the content with two questions:

1. Does the reader need action or cognition?
2. Is the reader acquiring skill or applying skill?

| Need | Reader State | Diataxis Type | Job |
| --- | --- | --- | --- |
| Action + acquisition | Learning through a managed path | Tutorial | Teach by guided doing. |
| Action + application | Working toward a goal | How-to guide | Help a competent reader complete a task. |
| Cognition + application | Working and checking facts | Reference | Describe exact facts for lookup. |
| Cognition + acquisition | Studying to understand | Explanation | Build conceptual understanding. |

If the user already names a type, use that type unless the artifact's user need clearly contradicts it. If it contradicts the label, state the mismatch briefly and apply the type that serves the reader.

## Workflow

1. Name the reader, their immediate need, and the artifact boundary.
2. Apply the compass and choose one primary Diataxis type for the page, section, or proposed artifact.
3. Write or revise to satisfy that type's contract.
4. Move off-type material into a linked page, a separate section with a different contract, a backlog note, or a deletion decision.
5. Verify current facts separately: commands, APIs, paths, product behavior, links, versions, and limits. Diataxis improves shape; it does not prove accuracy.

The work is complete when every changed page or section has one primary user need, off-type material has an intentional destination, and fragile claims are verified or explicitly flagged.

## Type Contracts

| Type | Use This Shape | Avoid |
| --- | --- | --- |
| Tutorial | One repeatable path, exact steps, visible results, expected observations, no alternatives. | Concept lectures, options, real-world branching, responsibility shifted to the learner. |
| How-to guide | A goal-oriented task flow for competent users, with conditionals for real cases. | Teaching basics, exhaustive option lists, tool tours, unexplained context switches. |
| Reference | Neutral, complete, consistent descriptions that mirror the product or API structure. | Instructions for a task, rationale, persuasion, incomplete parameter or behavior coverage. |
| Explanation | Context, why, trade-offs, history, constraints, and relationships. | Step-by-step tasks, raw lookup tables, advocacy, unbounded essays. |

Read `references/documentation-types.md` when authoring or reviewing a specific Diataxis type, especially when a boundary feels unclear.

Read `references/quality-and-structure.md` when reorganizing a docs set, designing landing pages, handling multiple audiences or environments, or reviewing documentation quality beyond type classification.

## Review Checklist

- Reader, need, and artifact boundary are explicit.
- The selected type follows from the compass.
- Language matches the type: guided, direct, austere, or discursive.
- Mixed material is split, linked, relocated, or intentionally removed.
- The page flow anticipates what the reader must hold in mind next.
- Fragile factual claims are checked against current sources.
- Navigation points readers to adjacent types instead of blending them inline.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Treating Diataxis as four mandatory headings | Create only the content the reader needs. |
| Calling a learning path a how-to guide | Use a tutorial when the reader is acquiring skill under guidance. |
| Turning a how-to guide into a lesson | Assume competence; link to tutorials or explanations for learning needs. |
| Explaining inside reference | Keep reference descriptive; link to explanation for rationale. |
| Pouring reference detail into tutorials | Keep the learner moving; link to reference for lookup. |
| Reorganizing before classifying small pieces | Classify and improve one page or section, then let the larger structure emerge. |

## Source Note

Adapted from `sammcj/agentic-coding` `Skills_disabled/diataxis-documentation` at commit `90f92c5b798dea83d83307fbc1b70bab9f4f39fa` (Apache-2.0).
