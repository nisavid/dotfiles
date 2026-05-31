# Global Agent Instructions

## Writing Policy

When writing specs, tests, documentation, comments, or durable agent instructions, describe the current desired behavior and source shape directly. Use historical contrast only when the history itself is the subject, and keep normative rules stated in terms of the current system.

## Pull Request Merge Policy

When multiple PR merge methods are available, prefer rebase merging by default. Do not use squash merging unless local repository policy requires it or the user explicitly requests it.

Local repository policy takes precedence over this general preference. If the user gives an in-context instruction that contradicts local repository policy, treat it as an override only when it is clear the user is aware of the policy and intends to override it. Otherwise, ask before acting.

## Tracking Branch Update Policy

Across repositories, keep local tracking branches current when doing so is safe. Before starting work from a branch such as `main`, check the worktree state, local-only commits, upstream branch, and branch relationship. If the branch is clean, checked out normally, has no local-only commits or unpushed work, and its upstream is ahead, treat pulling the upstream branch as implicitly intended.

Do not pull when it could disturb unstaged changes, uncommitted work, local-only commits, in-progress conflict resolution, detached or unusual checkout state, or a task-specific workflow that requires preserving the current branch state.

## Firecrawl Preference

Prefer task-specific tools for the specialized cases they are designed to handle. When Firecrawl skills are available and applicable, prefer the relevant Firecrawl skill as the general-purpose fallback for the web function it covers. Use lower-level or more generic web access methods only when no task-specific or Firecrawl skill fits, or another tool is explicitly required.

## Computer Use On Linux

When testing or using Computer Use on Linux, treat readiness as several separate
paths: window targeting, screenshots, AT-SPI accessibility, pointer input, raw
keyboard input, and text/paste input can succeed or fail independently. Run the
Computer Use readiness check first when practical, but do not infer that a
specific target app exposes useful semantic controls just because readiness is
green. Verify the target app with `get_app_state`; some apps expose only a
sparse AT-SPI root while screenshot, focus, and pointer input still work.

If ydotool diagnostics mention `Protocol wrong type for socket`, consider a
datagram-vs-stream socket probe mismatch before concluding that `ydotoold` is
missing or unusable. Recheck with the active backend build and socket-aware
diagnostics.

For AT-SPI issues, remember that some non-GNOME sessions still use the
historical `org.gnome.desktop.interface toolkit-accessibility` setting, and that
`NO_AT_BRIDGE=1` in the target app's environment can suppress toolkit bridges
even when the AT-SPI bus exists.

Keyboard input may be physical-keycode based. The active desktop layout,
remapped keys, and Compose-key configuration can transform literal key names and
shortcuts after Computer Use injects them. For literal text, shortcut, or key
parser tests, record the current layout before switching temporarily to a
standard US/QWERTY layout when possible, then restore the recorded layout after
the test. Prefer pointer clicks, screenshots, and file/clipboard verification
over visual guessing.

### Hatchery Computer Use

On hatchery, the desktop is KDE Plasma on Wayland with KWin window targeting and
XDG Desktop Portal screenshot/pointer paths. The usual layout indices are:

- `0`: `us(dvp)` / Programmer Dvorak, shown as `dvp`.
- `1`: `us(qw)` / English (US), shown as `qw`.

Use KDE's keyboard-layout D-Bus API for reversible layout tests:

```bash
qdbus6 org.kde.keyboard /Layouts org.kde.KeyboardLayouts.getLayout
qdbus6 --literal org.kde.keyboard /Layouts org.kde.KeyboardLayouts.getLayoutsList
qdbus6 org.kde.keyboard /Layouts org.kde.KeyboardLayouts.setLayout 1
qdbus6 org.kde.keyboard /Layouts org.kde.KeyboardLayouts.setLayout 0
```

For Computer Use key/text tests, record the starting layout. If the starting
layout is `0` (`dvp`), switch to layout `1` (`qw`) only for the test, then
restore the recorded layout. The user's Esc and Caps Lock are swapped, Right Alt
is Compose, and the Windows key is Meta. Avoid assuming physical Escape, Caps
Lock, AltGr, or Meta behavior; use window focus, screenshots, and explicit KDE
D-Bus state where possible.

## Context7

<!-- context7 -->
Use Context7 MCP to fetch current documentation whenever the user asks about a library, framework, SDK, API, CLI tool, or cloud service -- even well-known ones like React, Next.js, Prisma, Express, Tailwind, Django, or Spring Boot. This includes API syntax, configuration, version migration, library-specific debugging, setup instructions, and CLI tool usage. Use even when you think you know the answer -- your training data may not reflect recent changes. Prefer this over web search for library docs.

Do not use for: refactoring, writing scripts from scratch, debugging business logic, code review, or general programming concepts.

### Steps

1. Always start with `resolve-library-id` using the library name and the user's question, unless the user provides an exact library ID in `/org/project` format
2. Pick the best match (ID format: `/org/project`) by: exact name match, description relevance, code snippet count, source reputation (High/Medium preferred), and benchmark score (higher is better). If results don't look right, try alternate names or queries (e.g., "next.js" not "nextjs", or rephrase the question). Use version-specific IDs when the user mentions a version
3. `query-docs` with the selected library ID and the user's full question (not single words)
4. Answer using the fetched docs
<!-- context7 -->
