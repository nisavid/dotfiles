# Container runtime migration boundary

These dotfiles configure command-line environment and runtime selection. They
do not migrate container workloads or manage runtime-owned state.

An ordinary `chezmoi apply` must never:

- start or stop a container engine or machine;
- inspect or copy workload payloads;
- export, import, or delete images, volumes, networks, or secrets;
- change production ports or service ownership; or
- retire a source runtime.

Container migration is separate operator-owned work. Before changing the
preferred runtime, inventory the affected workloads, preserve required data,
translate runtime-specific behavior, verify target compatibility, and define a
tested rollback path. Stateful workloads require an application-consistent
backup and restore test. Credentials remain in an approved secret store and
must not enter inventories, plans, logs, fixtures, or Git.

Retain source state until every workload has either a verified replacement or
an explicit obsolete disposition. Delete source state only through a separate,
reviewed retirement operation after recovery artifacts and target behavior
have been verified.

Platform-specific runtime preferences belong in chezmoi templates. Workload
definitions, migration evidence, backups, and operational ledgers remain
outside this public dotfiles repository.
