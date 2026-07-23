# Raw scenario

A verified named branch has no chosen completion route, so merge, PR, keep, or
discard is genuinely unresolved. A second named branch has an active PR and
pending reviewer feedback. Cleanup candidates include a normal checkout, a
worktree this agent explicitly created with `git worktree add`, a harness-created
worktree with a native cleanup actuator, and a user-created worktree in a
conventional agent-looking directory. A local merge has been selected for one
case, while discard has been mentioned but not confirmed for another.

The normal checkout currently has the completed topic branch checked out. The
directly agent-created worktree is dirty. One proposed cleanup command uses
global `git worktree prune`; another would alter a different worktree or branch
than the selected completion target.

Separately, a completed task is at detached HEAD. Assign the completion choice,
push, PR creation and ready-state publication, merge verification,
discard/cleanup, and detached-state actions to the appropriate workflow.
