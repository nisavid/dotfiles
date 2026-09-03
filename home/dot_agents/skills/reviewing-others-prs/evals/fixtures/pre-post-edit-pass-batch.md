# Brief: edit three drafted comments before posting

You drafted three inline comments on a colleague's pull request. Before posting them for Ivan, run the edit pass over the batch and return the three revised comments, in order, separated by a line containing only `---`. Keep each comment's one ask and every `file:line`; the trailing "Also, …" requests are riders, not asks to keep.

## Facts you hold

- You read the diff. You did not run the tests, and CI has not reported on this head.
- `cache/store.py:57` reads `ttl = config.get("ttl", 0)` and passes it straight to `setex`, which raises on a zero TTL.
- `cache/store.py:12` imports `time` and never uses it.
- `cache/store.py:74` names the new helper `_purge_stale_keys` while the module's other helpers use the `_evict_*` prefix.

## Your drafts

In `cache/store.py:57` I noticed that `ttl = config.get("ttl", 0)` — the default of 0 — is handed straight to `setex`, which raises on zero, so this fails in CI. That said, could we default to `None` and skip `setex` when no TTL is configured? Also, the config schema should probably document the key.

---

In `cache/store.py:12` I noticed the `time` import is unused — worth noting that the linter is not enabled for this package. Let's drop it. Also, the file could use a module docstring.

---

In `cache/store.py:74` I noticed the new helper is named `_purge_stale_keys` — while the neighbours use `_evict_*` — which is a small inconsistency. That said, I'd rename it to `_evict_stale_keys` for consistency. Also, a test for it would be nice.
