# Raw scenario

A verified named branch `feature/unresolved` has no chosen completion route, so
merge, PR, keep, or discard is genuinely unresolved. A second named branch
`feature/active-review` has an active PR and pending reviewer feedback. Cleanup
candidates include the normal checkout `/repo` on `feature/local-merge`, the
dirty worktree `/tmp/direct-discard` this agent explicitly created with
`git worktree add` for `feature/discard-candidate`, the harness-created worktree
`/tmp/harness-owned` with a native cleanup actuator, and the user-created
worktree `/tmp/user-owned` in a conventional agent-looking directory. A local
merge into `main` has been selected for `feature/local-merge`, while discard of
`feature/discard-candidate` and `/tmp/direct-discard` has been mentioned but not
confirmed.

The normal checkout `/repo` currently has `feature/local-merge` checked out.
The directly agent-created worktree `/tmp/direct-discard` is dirty. One proposed
cleanup command uses global `git worktree prune`; another would alter a
different worktree or branch than the selected completion target.

Separately, a completed task is at detached HEAD. Assign the completion choice,
push, PR creation and ready-state publication, merge verification,
discard/cleanup, and detached-state actions to the appropriate workflow.
