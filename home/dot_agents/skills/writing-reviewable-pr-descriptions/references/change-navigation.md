# Change Navigation Reference

Use this reference only while constructing or revising the first-viewport
`STACK` and `DIFF` disclosures.

## Shared Badge Rules

- Every `<img>` has exactly one real `alt`, `src`, and `height="16"` attribute.
- Visible labels are uppercase.
- `STACK` and `DIFF` label shields use `style=for-the-badge` and neutral
  `57606A`; every metric shield uses `style=flat`.
- Category order is `IMPL`, `TEST`, `DOC`, `GEN`, `OTHER`, then `FILES`.
- Write category line metrics in Stack inventories, Diff summaries, and
  expanded Diff rows with grammatical count nouns: `1 addition` or
  `N additions`, and `1 deletion` or `M deletions`. Zero uses the plural form.
  For compatibility with stored bodies, validation also accepts the legacy
  plural noun when the count is exactly one.
- Colors are stable: `IMPL 0969DA`, `TEST 6F5F9A`, `DOC 3F7770`,
  `GEN 76652F`, `OTHER 57606A`, and `FILES 5F6B78`.
- Operation badges `BINARY`, `MOVED`, and `COPIED` use neutral `5F6B78`.
- The bounded Diff `REMAINDER` badge uses neutral `5F6B78`.
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
- Escape a branch-valued `BASE` message for the Shields path: double every `-`
  as `--` and every `_` as `__`, then percent-encode path separators such as
  `/` as `%2F` with uppercase escapes. Branch `release-1.2` renders as
  `BASE-release--1.2-5F6B78`.
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
- Separate a disclosure from following Markdown with a blank line. GitHub
  continues a raw HTML block to the next blank line, so a heading, list, table
  row, or paragraph on the line after `</details>` is swallowed into the
  disclosure's HTML and never parsed as Markdown. Raw HTML may follow
  immediately, which is how adjacent Stack and Diff disclosures render.

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
  only a branch-valued base such as `main` is a neutral unlinked badge. A
  branch-valued base is a conservative canonical branch name: 1 to 255
  characters drawn from `A-Za-z0-9`, `.`, `_`, `/`, and `-`; it may start with
  `_` but not with `-`, `.`, or `/`; it may not end with `.` or `/`; it may not
  be `HEAD` or contain `..` or `//`; and no `/`-separated component may start
  with `.` or end with `.lock`.
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
<summary><picture><img alt="DIFF" src="https://img.shields.io/badge/DIFF-57606A?style=for-the-badge" height="16"></picture>&nbsp;<picture><img alt="IMPL: 9 additions, 3 deletions" src="https://img.shields.io/badge/IMPL-%2B9%20%E2%88%923-0969DA?style=flat" height="16"></picture> <picture><img alt="TEST: 16 additions, 22 deletions" src="https://img.shields.io/badge/TEST-%2B16%20%E2%88%9222-6F5F9A?style=flat" height="16"></picture> <picture><img alt="FILES: 2 touched" src="https://img.shields.io/badge/FILES-2-5F6B78?style=flat" height="16"></picture></summary>

- <picture><img alt="IMPL: 9 additions, 3 deletions" src="https://img.shields.io/badge/IMPL-%2B9%20%E2%88%923-0969DA?style=flat" height="16"></picture> <picture><img alt="FILES: 1 implementation file" src="https://img.shields.io/badge/FILES-1-5F6B78?style=flat" height="16"></picture>
  - [`src/widget.ts`](https://github.com/OWNER/REPO/pull/101/files#diff-PATH_HASH) <picture><img alt="9 additions, 3 deletions" title="9 additions, 3 deletions" src="https://img.shields.io/badge/%2B9-%E2%88%923-CF222E?style=flat&labelColor=1A7F37" height="16"></picture>
- <picture><img alt="TEST: 16 additions, 22 deletions" src="https://img.shields.io/badge/TEST-%2B16%20%E2%88%9222-6F5F9A?style=flat" height="16"></picture> <picture><img alt="FILES: 1 test file" src="https://img.shields.io/badge/FILES-1-5F6B78?style=flat" height="16"></picture>
  - [`tests/widget.test.ts`](https://github.com/OWNER/REPO/pull/101/files#diff-PATH_HASH) <picture><img alt="16 additions, 22 deletions" title="16 additions, 22 deletions" src="https://img.shields.io/badge/%2B16-%E2%88%9222-CF222E?style=flat&labelColor=1A7F37" height="16"></picture>

</details>
```

### Diff Semantics

- Use a complete inventory for 100 or fewer touched files. Its summary category
  totals are additions/deletions from the exact pushed PR base/head. Omit
  categories with no changed lines. `FILES` is the total touched-file count,
  including binary and operation-only files. List every changed target path.
- Use a bounded inventory for more than 100 touched files. Select the first 100
  unique target paths in exact GitHub API order, then group only those selected
  paths in `IMPL`, `TEST`, `DOC`, `GEN`, `OTHER` order. Preserve relative API
  order within each group. `plan_diff_inventory` in
  `scripts/change_navigation/diff_inventory.py` implements this selection and
  aggregation contract. Never sort or group before selecting the 100 files.
- A bounded inventory keeps the existing Diff summary unchanged: full-diff
  semantic-category statlines in canonical order, followed by the full
  touched-file `FILES` count. Only the expanded view is bounded.
- Expanded top-level category items follow fixed category order. Each category
  metric is its full-diff addition/deletion total. A complete inventory labels
  its category file count normally. A bounded inventory labels it `N shown
  implementation files`, `N shown test files`, `N shown documentation files`,
  `N shown generated files`, or `N shown other files`, with correct singulars.
  The bounded counts sum to exactly 100; they never claim complete category file
  counts. Include `0 shown` with plural `files` when a positive full-diff
  category has no file among the selected 100.
- A bounded inventory ends with exactly these two rows. This example shows 530
  omitted files; the comparison SHAs equal the declared pushed base/head:

  ```md
  - <picture><img alt="REMAINDER: 530 changed files" src="https://img.shields.io/badge/REMAINDER-%2B530%20MORE-5F6B78?style=flat" height="16"></picture>
    - [Complete immutable comparison](https://github.com/OWNER/REPO/compare/BASE_SHA...HEAD_SHA)
  ```

  The link exposes the complete diff; the 100 displayed rows remain explicitly
  bounded. Use `1 changed file` for a remainder of one and `N changed files`
  otherwise. Reject missing or incorrect remainders, mutable refs, mismatched
  repositories or SHAs, and prose that calls the displayed rows complete.
- The planner owns the external GitHub API selection and grouping check. The
  body validator verifies the rendered structure and declared immutable
  identity; it cannot infer API order from Markdown alone. Do not hand-author
  or reorder the planner's selected rows.
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
- The per-file badge has matching `alt` and `title`. Write both with grammatical
  count nouns: `1 addition` or `N additions`, and `1 deletion` or
  `M deletions`. Zero uses the plural form. For compatibility with stored
  bodies, validation also accepts the legacy plural noun when the count is
  exactly one.
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
  rows, followed only by the canonical bounded remainder rows when applicable.
  Reject alternate list markers, prose, or other residual content.

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
  category. Otherwise use `OTHER` for that file's changed lines. A bounded
  inventory renders each of its 100 selected target paths exactly once; assign a
  mixed selected file to `OTHER` when one auditable category cannot own its row.
- Deleted file: link the path GitHub uses for the deletion anchor and count it as
  removed in Stack operations.
- Renamed stack title: refresh every linked title's `alt` and `title`, not only
  the visible list link.
- Large stack or diff: keep disclosures collapsed by default. Keep Stack
  inventories complete. Bound Diff file rows only through the 100-file contract
  above.
- Shields unavailable: meaningful `alt` text must leave the summaries and file
  metrics understandable.

## Validator Binding

Always bind validation to the destination PR so a self-consistent body for the
wrong PR cannot pass:

```bash
python3 "$HOME/.agents/skills/writing-reviewable-pr-descriptions/scripts/validate_change_navigation.py" \
  --repository OWNER/REPO --pr PR_NUMBER \
  --base-sha BASE_SHA --head-sha HEAD_SHA \
  /path/to/pr-body.md
```

Both the Stack current item and every Diff file link must match that repository
and PR number. A bounded Diff comparison must match that repository and the
declared base/head SHAs. The SHA options remain optional for a complete Diff,
but both are required to validate a bounded Diff.
