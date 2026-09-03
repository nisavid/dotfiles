# Brief: three inline comments on a colleague's CSV export PR

You are reviewing a colleague's pull request that adds a CSV export endpoint to a web service. You read the diff. You did not run the code or the tests. The PR description says the author "tested locally on a 200-row fixture". You are posting three inline comments for Ivan, one per finding, in the order below.

## Finding A: unbounded read in `export_csv` (blocks merge)

`export/handlers.py:41` does `rows = list(query.all())` before the handler starts writing, so the whole result set is held in memory. The query targets the `orders` table, which `docs/schema.md` puts at roughly 40 million rows in production. The handler already returns a `StreamingResponse`, so iterating the query with `query.yield_per(5000)` and writing rows as they arrive keeps memory flat regardless of table size. You want this fixed before merge. You have not observed the handler fail; a 200-row fixture would never show the problem.

## Finding B: unused imports (cleanup)

`export/handlers.py:3` imports `json` and `Optional`. Neither is used anywhere in the file.

## Finding C: parameter name (judgment call, not blocking)

The new endpoint at `export/handlers.py:37` names its format query parameter `fmt`. The two existing endpoints in the same file, `export_json` and `export_xlsx`, name the same parameter `format`. `format` shadows a Python builtin, which is a plausible reason the author chose `fmt`, and the existing endpoints already live with that shadowing. You lean toward `format` for consistency with the existing API surface, but you would not hold the PR over it.
