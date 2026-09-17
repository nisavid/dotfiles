# Hindsight templates

This repository retains reusable Hindsight templates and a reviewed release
pin. It supplies no active consumer binding. Ordinary chezmoi operations ignore
all Hindsight targets on every platform and leave existing files and data
untouched.

The reusable lifecycle is maintained in
[`nisavid/agents`](https://github.com/nisavid/agents/tree/main/tooling/hindsight).
Only `releaseCommit` and `releaseVersion` appear in public chezmoi data.

`tests/fixtures/hindsight-public.toml` supplies synthetic values for portable
rendering and source-ownership tests. Its explicit `hindsight.publicFixture`
override enables these test targets without loading a private catalog. The
tests apply the templates to temporary destinations and check their bytes and
private modes.

A real deployment requires a separately configured private consumer catalog
and a matching target-selection policy. Machine inventory, credential locators,
provider policy, account bindings, service identifiers, and private filesystem
layout belong in that encrypted catalog. The retained template adapter expects
`home/.private-hindsight.toml.age`; that file is not supplied by this repository.

Deployment and rollback procedures belong to the reusable lifecycle rather
than this consumer repository.
