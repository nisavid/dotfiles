# Choose lock and provenance authority

Type: grilling
Status: resolved

## Question

What role should the global `skills` lock play, and which artifact governs
deterministic restore and harness projections?

## Answer

A generated repo-owned resolved lock governs exact equipment inventory,
provider-route coverage, harness projections, and deterministic restore for
routes with reproducible artifacts. It also records native-rolling restore
classes and non-automated operation dispositions without promising exact
fresh-home restoration for those operations.
The native global `skills` lock remains useful manager-owned provenance and
import evidence; the update workflow should derive from it where useful instead
of hand-copying its inventory. It is not the sole authority because installed
`skills` 1.5.22 `experimental_install` consumes only a project lock, restores
only project `.agents/skills`, ignores global and agent projections in that
flow, and does not enforce recorded global folder hashes as integrity pins.
