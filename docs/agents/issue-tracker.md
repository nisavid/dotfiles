# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

Commands substitute values through shell variables such as `$n` and `$map`, and `gh api` paths use gh's own `{owner}`/`{repo}` substitution; angle brackets appear only in issue-body templates, never in a command, because the shell reads them as redirections.

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view "$n" --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment "$n" --body "..."`
- **Apply / remove labels**: `gh issue edit "$n" --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close "$n" --comment "..."`

Infer the repo from `git remote -v`; `gh` does this automatically when run inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view "$n" --comments` and `gh pr diff "$n"` for the diff.
- **List external PRs for triage**: `gh pr list --json` does not expose the author association, so use the REST list: `gh api 'repos/{owner}/{repo}/pulls?state=open&per_page=100' --paginate --jq '[.[] | {number, title, author_association}]'`, then keep only `author_association` of `CONTRIBUTOR`, `FIRST_TIMER`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view "$n" --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue. Create new children with `gh issue create --parent "$map"`; attach existing issues with `gh issue edit "$n" --parent "$map"` or `gh issue edit "$map" --add-sub-issue "$n"`. These flags need a recent `gh` (present in 2.97, absent in 2.23), so check capability first with `gh issue create --help | grep -q -- --parent`; when the flags are unavailable, use the API instead: `gh api --method POST "repos/{owner}/{repo}/issues/$map/sub_issues" -F sub_issue_id="$child_id"`, where `$child_id` is the child's numeric database id. Where sub-issues aren't enabled at all, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh api --method POST "repos/{owner}/{repo}/issues/$child/dependencies/blocked_by" -F issue_id="$blocker_id"`, where `$blocker_id` is the blocker's numeric **database id** (`gh api "repos/{owner}/{repo}/issues/$n" --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: read the map's children in map order with one GraphQL query, then pick the first open, unassigned, unblocked child:

  ```sh
  gh api graphql -f owner="$owner" -f repo="$repo" -F map="$map" -f query='
    query($owner: String!, $repo: String!, $map: Int!, $after: String) {
      repository(owner: $owner, name: $repo) {
        issue(number: $map) {
          subIssues(first: 100, after: $after) {
            pageInfo { hasNextPage endCursor }
            nodes {
              number
              state
              assignees(first: 1) { totalCount }
              blockedBy(first: 50) { nodes { state } }
            }
          }
        }
      }
    }'
  ```

  `subIssues` returns children in map order; keep that order. Paginate with `endCursor` while `hasNextPage` is true rather than trusting one page. The frontier ticket is the first node with `state == "OPEN"`, `assignees.totalCount == 0`, and no `blockedBy` node whose `state == "OPEN"` (`totalCount` also counts closed blockers, so never gate on it; a child with 50+ blockers needs its `blockedBy` connection paginated too). Stay inside this one response shape; do not mix in the REST `issue_dependencies_summary`. For a task-list map (the sub-issues fallback), parse the map body's checklist order, then `gh issue view "$n" --json state,assignees,body` per child; parse the issue numbers out of its `Blocked by:` body line and fetch each one's state (`gh issue view "$blocker" --json state`), since the child's own JSON carries only the child's state. Any blocker still open blocks the child.
- **Claim**: `gh issue edit "$n" --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment "$n" --body "$answer"`, then append a context pointer (gist + link) to the map's Decisions-so-far and re-read the map to verify the pointer landed, then `gh issue close "$n"` last. Closing last keeps the failure mode recoverable: a child is never closed without its map pointer, and a partial run resumes from whichever write is missing (each step is safe to re-check before re-writing).
