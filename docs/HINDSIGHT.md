# Hindsight consumer binding

The reusable Hindsight lifecycle is maintained in
[`nisavid/agents`](https://github.com/nisavid/agents/tree/main/tooling/hindsight).
This repository pins a reviewed release and supplies one encrypted consumer
binding.

The current binding is Darwin-only. On other platforms, `.chezmoiignore`
excludes every Hindsight target without deleting dormant files or data.

Machine inventory, credential locators, provider policy, account bindings,
service identifiers, and private filesystem layout live in
`home/.private-hindsight.toml.age`. Public templates consume that catalog.
`tests/fixtures/hindsight-public.toml` supplies synthetic values for portable
rendering and source-ownership tests.

Only `releaseCommit` and `releaseVersion` remain in public chezmoi data. They
identify the reusable release whose immutable installation is consumed by the
encrypted binding.

`hindsight-embed-service auth-refresh` refreshes the bound Codex session and
restarts the managed service only after login verification succeeds.

Deployment and rollback procedures belong to the reusable lifecycle rather
than this consumer repository.
