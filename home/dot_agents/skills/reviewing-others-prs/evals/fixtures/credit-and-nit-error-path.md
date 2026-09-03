# Brief: two inline comments on a validation refactor

You are reviewing a colleague's pull request that moves request validation in `svc/handlers.py` from the handler body into a decorator. You read the diff. You did not run the code. You are posting two inline comments for Ivan.

## Finding A: the new error message leaks an internal path (fix before merge)

The move is right: validating in the decorator at `svc/handlers.py:22` means every handler rejects a malformed body before touching the database, which the old per-handler checks did not guarantee. That is exactly what makes the new failure path matter: the decorator's error response at `svc/handlers.py:31` is `f"invalid body: {exc}"`, and `exc` for a schema failure includes the absolute path of the schema file on the server. Returning a fixed message and logging `exc` server-side closes the leak without losing the diagnostic. You want this fixed before merge.

## Finding B: type of the decorator's argument (nit)

`svc/handlers.py:19` types the `schema` argument as `Any`. The only callers pass a `Schema` instance. Trivial, and you would not hold the PR over it.
