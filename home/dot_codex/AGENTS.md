## Writing Policy

When writing specs, tests, documentation, comments, or durable agent instructions, describe the current desired behavior and source shape directly. Use historical contrast only when the history itself is the subject, and keep normative rules stated in terms of the current system.

## Pull Request Merge Policy

When multiple PR merge methods are available, prefer rebase merging by default. Do not use squash merging unless local repository policy requires it or the user explicitly requests it.

Local repository policy takes precedence over this general preference. If the user gives an in-context instruction that contradicts local repository policy, treat it as an override only when it is clear the user is aware of the policy and intends to override it. Otherwise, ask before acting.

## Tracking Branch Update Policy

Across repositories, keep local tracking branches current when doing so is safe. Before starting work from a branch such as `main`, check the worktree state, local-only commits, upstream branch, and branch relationship. If the branch is clean, checked out normally, has no local-only commits or unpushed work, and its upstream is ahead, treat pulling the upstream branch as implicitly intended.

Do not pull when it could disturb unstaged changes, uncommitted work, local-only commits, in-progress conflict resolution, detached or unusual checkout state, or a task-specific workflow that requires preserving the current branch state.

<!-- context7 -->
Use Context7 MCP to fetch current documentation whenever the user asks about a library, framework, SDK, API, CLI tool, or cloud service -- even well-known ones like React, Next.js, Prisma, Express, Tailwind, Django, or Spring Boot. This includes API syntax, configuration, version migration, library-specific debugging, setup instructions, and CLI tool usage. Use even when you think you know the answer -- your training data may not reflect recent changes. Prefer this over web search for library docs.

Do not use for: refactoring, writing scripts from scratch, debugging business logic, code review, or general programming concepts.

## Steps

1. Always start with `resolve-library-id` using the library name and the user's question, unless the user provides an exact library ID in `/org/project` format
2. Pick the best match (ID format: `/org/project`) by: exact name match, description relevance, code snippet count, source reputation (High/Medium preferred), and benchmark score (higher is better). If results don't look right, try alternate names or queries (e.g., "next.js" not "nextjs", or rephrase the question). Use version-specific IDs when the user mentions a version
3. `query-docs` with the selected library ID and the user's full question (not single words)
4. Answer using the fetched docs
<!-- context7 -->
