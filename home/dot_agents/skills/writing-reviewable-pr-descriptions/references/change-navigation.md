# Change Navigation Reference

Use this reference only while constructing or revising the first-viewport
`STACK` and `DIFF` disclosures.

## Shared Badge Rules

- Every `<img>` has exactly one real `alt`, `src`, and `height="16"` attribute.
- Visible labels are uppercase.
- `STACK` and `DIFF` label shields use `style=for-the-badge` and neutral
  `57606A`; every metric shield uses `style=flat`.
- Category order is `IMPL`, `TEST`, `DOC`, `GEN`, `OTHER`, then `FILES`.
- Colors are stable: `IMPL 0969DA`, `TEST 6F5F9A`, `DOC 3F7770`,
  `GEN 76652F`, `OTHER 57606A`, and `FILES 5F6B78`.
- Operation badges `BINARY`, `MOVED`, and `COPIED` use neutral `5F6B78`.
- Encode badge text for URLs. Use the true minus sign `−` (`%E2%88%92`), not a
  hyphen, in visible deletion metrics.
- Separate the label shield from metrics with `&nbsp;`; use ordinary spaces
  between subsequent shields.
- Wrap non-navigation images in `<picture>`. Link only intentional PR
  navigation badges.
- Linked PR badges have matching descriptive `alt` and `title` text containing
  `#number — recognizable title`. Escape HTML special characters.
- Atomic line badges and `BINARY`, `MOVED`, and `COPIED` badges have exactly one
  `title` matching their `alt`. Other badges have no `title`.
- Encode Shields paths canonically with uppercase percent escapes. Do not use
  alternate-but-equivalent encodings such as a raw `+` or lowercase `%2b`.
- Use real `src`, `height`, `alt`, and `title` attributes. Attributes such as
  `data-src` and `data-title` do not satisfy the contract.
- Every `<img>` inside either disclosure is a structurally valid Shields image
  with a real `src="https://img.shields.io/..."`; do not leave inert, fallback,
  or non-Shields images in recognized navigation markup.
- Keep every summary on one source line. GitHub disclosure rendering is less
  predictable when block markup appears inside `<summary>`. Each disclosure
  contains exactly one `<summary>...</summary>` pair.
- Render exactly one Stack disclosure when stacked and exactly one Diff
  disclosure in every body. They form the leading `[STACK, DIFF]` or `[DIFF]`
  prefix; unrelated disclosures may follow, but must not interrupt that prefix.

## Stack Disclosure

Render this only for a stacked PR, immediately before Diff:

```md
<details>
<summary><picture><img alt="STACK" src="https://img.shields.io/badge/STACK-57606A?style=for-the-badge" height="16"></picture>&nbsp;<picture><img alt="STACK POSITION: 2 OF 2" src="https://img.shields.io/badge/2%20OF%202-5F6B78?style=flat" height="16"></picture> <a href="https://github.com/OWNER/REPO/pull/100"><img alt="BASE: #100 — feat(api): add request contract" title="#100 — feat(api): add request contract" src="https://img.shields.io/badge/BASE-%23100-5F6B78?style=flat" height="16"></a> <picture><img alt="STACK STATUS: TOP" src="https://img.shields.io/badge/TOP-5F6B78?style=flat" height="16"></picture></summary>

- **[#100 — feat(api): add request contract](https://github.com/OWNER/REPO/pull/100)**<br><picture><img alt="IMPL: 32 additions, 4 deletions" src="https://img.shields.io/badge/IMPL-%2B32%20%E2%88%924-0969DA?style=flat" height="16"></picture> <picture><img alt="TEST: 18 additions, 0 deletions" src="https://img.shields.io/badge/TEST-%2B18%20%E2%88%920-6F5F9A?style=flat" height="16"></picture> <picture><img alt="FILES: 2 added, 1 modified, 0 removed" src="https://img.shields.io/badge/FILES-%2B2%20~1%20%E2%88%920-5F6B78?style=flat" height="16"></picture>

- **[#101 — feat(web): consume request contract](https://github.com/OWNER/REPO/pull/101)** **← this PR**<br><picture><img alt="IMPL: 20 additions, 8 deletions" src="https://img.shields.io/badge/IMPL-%2B20%20%E2%88%928-0969DA?style=flat" height="16"></picture> <picture><img alt="TEST: 16 additions, 22 deletions" src="https://img.shields.io/badge/TEST-%2B16%20%E2%88%9222-6F5F9A?style=flat" height="16"></picture> <picture><img alt="FILES: 0 added, 6 modified, 0 removed" src="https://img.shields.io/badge/FILES-%2B0%20~6%20%E2%88%920-5F6B78?style=flat" height="16"></picture>

<sup>IMPL means non-test source and configuration. TEST, DOC, GEN, and OTHER are counted separately. FILES shows added, modified, and removed files as +, ~, and −.</sup>

</details>
```

### Stack Semantics

- Position is the current PR's one-based index over the complete current stack.
- `BASE` is the direct Git base. A PR-valued `BASE` always links to that PR;
  only a branch-valued base such as `main` is a neutral unlinked badge.
- Add `DEP` badges immediately after `BASE` only for additional PR dependencies.
  Do not repeat the direct base or any member of the Stack inventory as a
  dependency; ancestry already represented by the direct-base chain is
  transitive. For the bottom inventory item, a PR-valued `BASE` is outside the
  inventory.
- `NEXT` links to the next PR when one follows. `TOP` is an unlinked endpoint.
- Every intentionally linked `BASE`, `DEP`, or `NEXT` badge uses the destination
  PR's title in `alt` and `title`.
- Expanded content lists the complete stack from bottom to top. Each item has a
  bold title link, one `<br>`, then an unlabeled metric row on the same source
  line. Mark exactly one item `**← this PR**`.
- Escape `\`, backticks, `*`, `_`, `[`, and `]` with one backslash in each
  visible inventory title, and use canonical HTML entities for `&`, `<`, and
  `>`. The resulting plain title must exactly match the corresponding
  navigation badge's semantic title.
- Stack `FILES` always shows added, modified, and removed counts, even when zero.
  Append `MOVED N` and `COPIED N` in that order when nonzero; for example,
  `+0 ~1 −0 MOVED 1 COPIED 2`.
- Added, modified, removed, moved, and copied are disjoint file operations. For
  the current Stack item, their sum equals the Diff summary's touched-file
  count. `MOVED` and `COPIED` counts exactly match the Diff file rows carrying
  those operation badges; the remaining unique Diff target paths equal the
  added-plus-modified-plus-removed subtotal.
- Use the exact taxonomy line shown in the example. A short current contextual
  note, such as a recently merged former base, may follow it using inline prose,
  links, and code only.
- Do not put Stack or Diff label shields inside the expanded list.
- Do not repeat this inventory in a separate `## Stack` section.
- The expansion contains only its canonical inventory rows, the exact taxonomy
  `<sup>` line, and at most one short inline contextual line after the taxonomy.
  Do not use headings, tables, quotes, fences, HTML blocks, images, alternate
  list markers, or text or extra badges appended to an inventory row.

## Diff Disclosure

Render this for every PR, immediately after Stack when present. Resolve the
exact pushed base/head first; stop rather than publish when it is unavailable:

```md
<details>
<summary><picture><img alt="DIFF" src="https://img.shields.io/badge/DIFF-57606A?style=for-the-badge" height="16"></picture>&nbsp;<picture><img alt="IMPL: 20 additions, 8 deletions" src="https://img.shields.io/badge/IMPL-%2B20%20%E2%88%928-0969DA?style=flat" height="16"></picture> <picture><img alt="TEST: 16 additions, 22 deletions" src="https://img.shields.io/badge/TEST-%2B16%20%E2%88%9222-6F5F9A?style=flat" height="16"></picture> <picture><img alt="FILES: 6 touched" src="https://img.shields.io/badge/FILES-6-5F6B78?style=flat" height="16"></picture></summary>

- <picture><img alt="IMPL: 20 additions, 8 deletions" src="https://img.shields.io/badge/IMPL-%2B20%20%E2%88%928-0969DA?style=flat" height="16"></picture> <picture><img alt="FILES: 3 implementation files" src="https://img.shields.io/badge/FILES-3-5F6B78?style=flat" height="16"></picture>
  - [`src/widget.ts`](https://github.com/OWNER/REPO/pull/101/files#diff-PATH_HASH) <picture><img alt="9 additions, 3 deletions" title="9 additions, 3 deletions" src="https://img.shields.io/badge/%2B9-%E2%88%923-CF222E?style=flat&labelColor=1A7F37" height="16"></picture>
- <picture><img alt="TEST: 16 additions, 22 deletions" src="https://img.shields.io/badge/TEST-%2B16%20%E2%88%9222-6F5F9A?style=flat" height="16"></picture> <picture><img alt="FILES: 1 test file" src="https://img.shields.io/badge/FILES-1-5F6B78?style=flat" height="16"></picture>
  - [`tests/widget.test.ts`](https://github.com/OWNER/REPO/pull/101/files#diff-PATH_HASH) <picture><img alt="16 additions, 22 deletions" title="16 additions, 22 deletions" src="https://img.shields.io/badge/%2B16-%E2%88%9222-CF222E?style=flat&labelColor=1A7F37" height="16"></picture>

</details>
```

### Diff Semantics

- Summary category totals are additions/deletions from the exact pushed PR
  base/head. Omit categories with no changed lines. `FILES` is total touched
  files, including binary and operation-only files.
- Expanded top-level items follow fixed category order. Each has the same
  category total plus the number of files included in that category. Use these
  exact descriptors: `implementation`, `test`, `documentation`, `generated`,
  and `other`, with singular `file` or plural `files`.
- Nested items link every changed path to its actual Files changed anchor. Hash
  the exact GitHub diff path with SHA-256 only when GitHub's anchor convention
  is confirmed; otherwise read and verify the anchor from GitHub.
- Render an ordinary path as Markdown inline code inside the link. When the
  semantic path contains a backtick, use
  `<a href="FILES_URL"><code>HTML-ESCAPED_PATH</code></a>` instead; HTML-escape
  `&`, `<`, and `>` canonically and hash the unescaped target path. Do not use
  the HTML form for paths that the ordinary Markdown form can represent.
- Each textual file has one atomic two-segment shield. Green `1A7F37` is the
  label segment and red `CF222E` the message segment. Because both values are one
  image, a browser cannot break a line between additions and deletions.
- A file row contains only that atomic shield, or one `BINARY`, `MOVED`, or
  `COPIED` operation shield followed by the permitted atomic shield. Do not add
  category, file-count, or navigation shields to a file row.
- The per-file badge has matching `alt` and `title`, both written as words:
  `N additions, M deletions`.
- Use `+0` or `−0` when one side is zero. For a binary file with no meaningful
  line counts, use one neutral `BINARY` badge with matching `alt` and `title`.
- For a move or copy, give the source and target separate code nodes inside one
  link: ``[`old` → `new`](FILES_URL)``. A literal ` → ` inside either code node
  remains part of that path. When either path contains a backtick, use
  `<a href="FILES_URL"><code>HTML-ESCAPED_OLD</code> → <code>HTML-ESCAPED_NEW</code></a>`.
  Add a neutral `MOVED` or `COPIED` badge. The operation badge comes first; if
  the file also has edits, append the atomic line badge. Count it in the target
  path's semantic category; use `OTHER` only when the target cannot be
  classified reliably.
- A category may appear only in the expanded view with `+0 −0` when it contains
  only binary or operation-only files. The summary still omits its zero-line
  metric; the summary `FILES` count preserves its presence.
- Use singular `file` and plural `files` correctly in group badges.
- The expansion contains only canonical category rows and their indented file
  rows. Reject alternate list markers, prose, or other residual content.

## Edge Checks

- Empty diff: do not fabricate a Diff disclosure. State that the pushed
  base/head has no diff and resolve whether the PR target or push is wrong.
- Changed base or restack: recompute every PR independently; never reuse totals
  from a previous base.
- Mixed file: split additions/deletions by category only when the patch supports
  an auditable split. In that case, the same linked file may appear once in each
  applicable category, while the summary `FILES` badge counts its target path
  once. Every appearance of the same target path uses the same operation kind
  and, for a move or copy, the same source path. Never repeat a file within one
  category. Otherwise use `OTHER` for that file's changed lines.
- Deleted file: link the path GitHub uses for the deletion anchor and count it as
  removed in Stack operations.
- Renamed stack title: refresh every linked title's `alt` and `title`, not only
  the visible list link.
- Large stack or diff: keep the disclosures collapsed by default; do not truncate
  the complete inventory merely to shorten the source.
- Shields unavailable: meaningful `alt` text must leave the summaries and file
  metrics understandable.

## Validator Binding

Always bind validation to the destination PR so a self-consistent body for the
wrong PR cannot pass:

```bash
python3 "$HOME/.agents/skills/writing-reviewable-pr-descriptions/scripts/validate_change_navigation.py" \
  --repository OWNER/REPO --pr PR_NUMBER /path/to/pr-body.md
```

Both the Stack current item and every Diff file link must match that repository
and PR number.
