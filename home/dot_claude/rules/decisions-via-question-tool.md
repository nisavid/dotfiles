# Decisions Via The Question Tool

Whenever you need Ivan's attention, call the `AskUserQuestion` tool in the same turn, after your prose status: for a decision or approval, a list of options, "which do you want?", a clarification, a blocker that needs him, "tell Ivan", or an action only he can take. Put the recommended option first and the facts in the option descriptions. Without the tool, as in a subagent or a headless run, hand the question back to your caller instead.

A mention in prose is not telling Ivan. Assume every response is lost in a near-constant stream of handoffs and dispatches unless the tool prompts him.

Before ending any turn in a long-running role (foreman, orchestrator, coordinator), check your text for a question aimed at Ivan, a list of options, "your call", "let me know", "tell Ivan", or an item blocked on him. If you find one, call the tool before the turn ends.

Obviously safe corrections within your own remit are the exception: make them; don't ask.

Ivan corrected this on 2026-09-29, 2026-10-02 (twice), and 2026-10-16; the memory alone did not prevent recurrence.
