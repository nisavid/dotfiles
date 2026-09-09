---
name: capturing-agent-procedures
description: Use when planning, executing, reviewing, or completing work that establishes a reusable agent procedure, corrects an existing method, or depends on a procedure another task produces, across design, development, operations, and adoption.
---

# Capturing Agent Procedures

Make reusable methods discoverable and executable by the next agent. Capture them as part of the producing work's completion contract; connect dependent work to the reviewed procedure.

## Identify The Capture

Inspect the active brief, implementation, corrections, and existing equipment before choosing a change. Use `extending-managed-skills` to establish source ownership and `honing-agent-facing-docs` for placement and discovery. Search related tasks for an existing producer before creating one.

| Evidence | Action |
| --- | --- |
| Existing equipment covers the method | Use it; incorporate a useful correction into its maintained source. |
| A new reusable method has a distinct trigger | Capture it in focused equipment and add the minimum invocation pointer. |
| Correctness, generality, placement, or tradeoffs remain uncertain | Prepare the proposal below and wait for the human decision. |
| Routine work adds no reusable method or correction | Finish through the existing workflow; no equipment change is needed. |

Put project-specific methods in repo-carried equipment. Put broadly applicable methods in user-global equipment through its owning source repository. Repo scope can provisionally establish a method whose local use is supported; broader promotion remains a proposal. Preserve plugin, lockfile, and upstream-owned bases, using a local extension where needed. Maintain one source and the harness's standard projections, including Claude symlinks when applicable.

For an uncertain change, record a concrete proposal in the task's authorized notes or tracker: intended behavior and source, evidence and limits, useful consumers, tradeoff, and the decision needed. Use `grilling` to present it and wait for the response. Keep unsettled behavior out of installed conventions. Continue independent authorized work; if tracker updates are outside scope, return the proposal in the task instead.

## Select The Work

For new equipment or a useful correction, follow [references/producing.md](references/producing.md), then connect consumers below. For an unchanged reviewed procedure, proceed directly to consumer verification; its existing evidence remains usable while the candidate and relevant dependencies are unchanged. Routine work with no capture or consumption finishes through its existing workflow.

## Connect And Verify Consumers

Update authorized downstream task instructions with the skill name, maintained source, invocation condition, and required producer result. Use real prerequisite dependencies where a consumer needs the validated procedure, following the tracker or harness's native mechanism. Where no dependency actuator exists, record an explicit blocking prerequisite in the owning task. Let independent work continue; split dependent work when needed to avoid blocking unrelated progress.

Consumers load the procedure before dependent execution, record the source revision they used, verify outputs against its completion criteria, and feed useful corrections back to the producer. Producer self-use records the candidate revision and validates it without depending on itself. Verify the resulting dependency graph has no cycles.

A producer finishes capture only when the maintained source and invocation pointers are present, final review and behavior evidence are current, authorized publication and targeted installation are verified, and consumers can locate the reviewed revision. Report the source, reviewed revision, evidence, installation and projection status, and unresolved proposals. Keep human acceptance, publication, and domain decisions with their existing owners; this procedure grants no additional mutation authority.
