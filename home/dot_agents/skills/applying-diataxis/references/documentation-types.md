# Diataxis Documentation Types

Load this reference when writing, reviewing, or repairing one Diataxis type, or when a page mixes two types and the boundary decision matters.

## Contents

- Tutorials
- How-to Guides
- Reference
- Explanation
- Boundary Checks

## Tutorials

A tutorial is a managed learning experience. The reader is acquiring skill by doing, and the author is responsible for the learner reaching a successful result.

### Contract

- Lead one concrete path from start to visible finish.
- State where the learner is going before they start.
- Use exact commands, files, inputs, outputs, and checkpoints.
- Produce visible results early and repeatedly.
- Tell the learner what to notice after important steps.
- Minimize explanation; link away for deeper rationale.
- Remove alternatives, optional branches, and open-ended decisions.
- Test the path until every step works from the stated starting point.

### Voice

Use guided language: "Create...", "Run...", "You should see...", "Notice...". The tone can be supportive, but the content still needs exactness.

### Good Shape

````markdown
# Build Your First Webhook Receiver

In this tutorial, you will create a local endpoint, receive a test webhook, and inspect the payload.

## Create the endpoint

Create `server.js`:

[complete code]

## Start the server

Run:

```bash
node server.js
```

You should see:

```text
Listening on http://localhost:3000
```

Notice that the server stays open; leave this terminal running for the next step.
````

### Smells

- The page explains concepts before the learner has done anything.
- The learner must choose between multiple tools or approaches.
- The steps assume domain competence not established by the tutorial.
- Expected output is missing, vague, or impossible to compare.
- Failures are pushed onto the learner instead of prevented by the path.

## How-to Guides

A how-to guide helps a competent reader accomplish a real task. The reader is applying skill and can adapt directions to their context.

### Contract

- Name the practical goal: "How to [achieve result]".
- Start from a realistic working point, not always from scratch.
- Order steps by the reader's workflow, not just by implementation detail.
- Use conditionals for real-world variation: "If X, do Y."
- Keep the guide selective; link to reference for complete option sets.
- Keep concepts brief; link to explanation for rationale.
- Minimize context switching between tools, pages, files, and mental states.

### Voice

Use direct task language: "To...", "If...", "For production...", "When...". Assume the reader knows the domain and wants momentum.

### Good Shape

````markdown
# How to Rotate API Keys

Use this guide when an existing key must be replaced without interrupting clients.

## Create the replacement key

[task steps]

## Deploy clients with both keys accepted

If clients update in batches, keep the old key active until all batches report the new key.

## Remove the old key

[task steps]

For field definitions, see the API key reference.
````

### Smells

- The page teaches basic concepts before acting.
- The title names a tool instead of a result.
- It lists every option instead of the options relevant to the task.
- It leaves a concern open for many steps before resolving it.
- It jumps between files or tools when grouping would preserve flow.

## Reference

Reference describes facts a reader consults while working. It is neutral, complete for its scope, and structured like the product or API it describes.

### Contract

- Describe what exists, what it does, and how it behaves.
- Mirror the product, API, command, schema, or file structure.
- Use consistent sections and order for repeated objects.
- Cover parameters, fields, return values, errors, defaults, constraints, and warnings that belong to the scope.
- Provide small examples only to illustrate usage shape, not to teach a task.
- Keep rationale and task instructions out; link to explanation or how-to guides.

### Voice

Use austere factual language: "`timeout` is...", "Valid values are...", "Raises...", "Default...". Avoid persuasion and narrative.

### Good Shape

````markdown
# `createToken(options)`

Creates an authentication token.

## Parameters

- `subject` (string, required): Token subject.
- `expiresIn` (integer, optional): Lifetime in seconds. Default: `3600`.

## Returns

`Token` with `value`, `expiresAt`, and `subject`.

## Errors

- `InvalidSubjectError`: `subject` is empty or malformed.

## Example

```js
createToken({ subject: "user_123", expiresIn: 900 })
```
````

### Smells

- It tells readers how to accomplish a broader task.
- It explains why the design exists.
- Similar objects use different section orders.
- Completeness is sacrificed for readability without a clear scope decision.
- The structure diverges from the product and makes lookup harder.

## Explanation

Explanation helps readers understand a topic. It supports study through concepts, context, trade-offs, and relationships.

### Contract

- Discuss why the system works this way.
- Connect related concepts and show constraints.
- Include history, trade-offs, and design rationale when they help understanding.
- Present perspectives without turning into advocacy.
- Keep task steps and raw lookup detail out; link to how-to or reference pages.
- Bound the topic so the page has a clear center.

### Voice

Use discursive language: "The reason...", "This trade-off...", "Compared with...", "Historically...".

### Good Shape

````markdown
# About Token Expiration

Short token lifetimes reduce the time a stolen token remains useful. They also increase refresh traffic and make client clock drift more visible.

The system uses short access tokens with longer-lived refresh tokens because...

For rotation steps, see the key rotation guide. For exact fields, see the token reference.
````

### Smells

- The page becomes a how-to guide with commands.
- The page becomes reference with exhaustive fields and defaults.
- It argues for a feature instead of explaining trade-offs.
- It drifts across too many concepts without a boundary.

## Boundary Checks

| If You See | It Probably Belongs In |
| --- | --- |
| "Follow these steps to learn..." | Tutorial |
| "To accomplish this goal..." | How-to guide |
| "The valid values are..." | Reference |
| "The reason this exists..." | Explanation |
| Beginner path with choices and branches | Split: tutorial path plus how-to or explanation links |
| Task guide with long conceptual detours | How-to guide plus linked explanation |
| Reference table with usage workflow | Reference plus linked how-to guide |
| Concept page with commands | Explanation plus linked how-to guide |
