# Pressure Scenarios

Use these scenarios when revising `triaging-agent-armory-issues`.

## Bulk L1 Drift

Prompt: "Bulk triage all untriaged Agent Armory issues at level 1."

Baseline failure to catch: the agent follows the generic triage skill, explores
the codebase for every issue, and emits category/state only.

Expected behavior: process issues one at a time from body/comments only; assign
or recommend category, state, depth, work kind, and engagement labels; stop and
route issues that need linked context or deep sessions.

## Implementable But Mis-specified

Prompt: "Triage this issue as ready-for-agent; the requested change is clear."

Baseline failure to catch: the agent accepts the written specification without
checking whether it preserves underlying Armory intent.

Expected behavior: perform at least L1 reflection; if the spec is poor or the
intent is unsettled, use `needs-info`, `needs-triage`, `brief:needed`, or a
deeper engagement mode instead of delegating.

## Label Drift Audit

Prompt: "What needs triage in Agent Armory?"

Baseline failure to catch: the agent lists unlabeled and `needs-triage` issues
without checking whether the current baseline axes are internally consistent.

Expected behavior: when bulk dogfooding or drift is plausible, run or recommend
`tools/issue_tracker_ops.py audit-labels` and interpret missing/conflicting
axis labels before proposing bulk handling.
