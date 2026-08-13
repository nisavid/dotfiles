# Diataxis Quality and Structure

Load this reference when reviewing quality, reorganizing a documentation set, designing navigation, or handling multiple audiences, platforms, or maturity levels.

## Contents

- Quality Layers
- Multi-Page Structure
- Complex Audience and Environment Cases
- Landing Pages
- Iterative Repair
- Review Heuristics

## Quality Layers

Diataxis improves documentation shape and reader fit. It does not replace technical verification.

### Functional Quality

Functional quality is objective enough to check:

- Accuracy: claims match the product.
- Completeness: the stated scope covers what it promises.
- Consistency: pages do not contradict each other.
- Precision: terms, commands, paths, and values are unambiguous.
- Usefulness: the page serves a real reader need.

Verify functional quality against source code, product behavior, current docs, generated references, command output, or product owners. Do not assume Diataxis classification makes facts correct.

### Felt Quality

Felt quality is what makes documentation feel right to use:

- The page has flow.
- The next needed fact or action appears when the reader needs it.
- The shape fits the reader's work or study state.
- The document feels calm, predictable, and humane.

Felt quality depends on functional quality. A beautiful page with stale commands fails as documentation.

## Multi-Page Structure

A documentation set does not need every Diataxis type for every feature. Provide the types that real readers need.

Common shapes:

- New or complex feature: tutorial, how-to guide, reference, and explanation.
- Established workflow: how-to guide plus reference.
- Simple API or command: reference only.
- Concept-heavy system: explanation plus reference, with how-to guides for common tasks.

Structure follows user needs before taxonomy. Avoid creating empty pages just to fill the compass.

## Complex Audience and Environment Cases

When several dimensions collide, choose the navigation order readers actually use.

### Multiple Audiences

End users, API consumers, operators, and contributors may experience the same product as different products.

Use separate paths when:

- They have different prerequisites.
- They perform different tasks.
- They need different safety warnings.
- They consult different reference material.

Let shared concept pages or shared reference pages serve several paths only when the content is genuinely common.

### Multiple Platforms or Environments

Cloud, on-prem, local, and managed deployments may require different workflows.

Use separate pages when the steps diverge enough that conditionals would disrupt flow. Use one page with conditionals when most of the task is shared and the differences are local.

### Maturity Levels

Basic and advanced content can exist within any Diataxis type. Advanced tutorials still teach through guided doing. Basic how-to guides still assume the reader is applying skill to a task.

Do not use "advanced" as a substitute for choosing the right type.

## Landing Pages

Landing pages should orient, not just list.

Good landing pages:

- State who the section is for.
- Group links by reader goal, audience, environment, or lifecycle stage.
- Keep groups small enough to scan.
- Add one or two sentences that tell readers how to choose.
- Link to adjacent Diataxis types without merging their content.

Lists longer than about seven items need grouping unless there is a mechanical order such as alphabetical or numeric order.

Example shape:

```markdown
## Operate the Service

Use these guides when you are maintaining a running deployment.

### Deployments

- How to deploy a new version
- How to roll back a deployment

### Incidents

- How to inspect service health
- How to collect diagnostic logs
```

## Iterative Repair

Large docs sets rarely need a one-shot rewrite. Improve them one piece at a time:

1. Choose a page, section, or paragraph.
2. Name the reader need it should serve.
3. Classify it with the compass.
4. Find the highest-value mismatch: wrong type, off-type material, stale fact, missing flow, or poor navigation.
5. Make one coherent improvement.
6. Repeat.

This keeps the docs useful during the work and lets structure emerge from repaired content.

## Review Heuristics

### Boundary Violations

- Tutorial contains long conceptual explanation: extract or link to explanation.
- Tutorial offers choices: keep one path; move alternatives to how-to or explanation.
- How-to guide teaches basic concepts: assume competence; link to tutorial or explanation.
- How-to guide lists full option sets: link to reference.
- Reference tells readers how to solve a task: move instructions to a how-to guide.
- Reference explains design rationale: move rationale to explanation.
- Explanation includes commands: move steps to how-to or tutorial.

### Flow Problems

- The reader must remember unresolved context across too many steps.
- The page jumps between files, tools, dashboards, or mental models unnecessarily.
- Expected outputs or decision points arrive after the reader needs them.
- A link interrupts the main path instead of supporting it.

### Navigation Problems

- A docs index is only a file list.
- Similar pages live under unrelated headings.
- The same fact has multiple homes.
- Different audiences are forced through one path.
- The page title does not reveal the reader goal or topic.

### Accuracy Problems

- Commands, screenshots, paths, API fields, defaults, limits, or version claims are unverified.
- Generated reference has manual edits without a regeneration note.
- "Latest", "current", or "new" appears without a current source check.
- A tutorial was not run from a clean start.

## Closeout Standard

A Diataxis review is clean when:

- Every changed page has a primary type and reader need.
- Adjacent types are linked, not blended.
- Navigation routes readers by goal or topic.
- Off-type or removed material has a clear disposition.
- Fragile facts are verified or marked as unverified work.
- Remaining limitations are explicit and scoped.
