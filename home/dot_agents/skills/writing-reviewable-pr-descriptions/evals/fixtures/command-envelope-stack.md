# Command-envelope stack

Repository: `example/control-plane`

Pull request: `#202`, draft, second of four. Exact pushed stack and per-PR
base/head SHAs are already resolved. The required Stack and Diff disclosures are
already collapsed, valid, and must remain first.

Stack contract:

1. `#201` adds the versioned command schema and persistence table.
2. `#202` (this PR) makes the CLI and API produce one command envelope, makes
   the worker consume it, and retains a direct-execution compatibility adapter.
3. `#203` switches the web UI and scheduled jobs to the envelope.
4. `#204` removes the compatibility adapter after all producers migrate.

Current PR facts:

- 48 files changed: 1,140 authored implementation/test lines and 9,800
  generated schema/client lines.
- The current contract is `kind`, `version`, `tenant`, idempotency key, payload,
  and trace context.
- CLI and API are the only migrated producers in this PR.
- The worker validates version and tenant before dispatch.
- The compatibility adapter preserves direct execution for the web UI and
  scheduler until later PRs; it logs which legacy producer used it.
- Queue ownership, retry policy, UI migration, scheduler migration, and adapter
  deletion are outside this PR.
- The relevant authored surfaces are the envelope type and validation, CLI/API
  construction, worker dispatch and idempotency, the compatibility adapter and
  telemetry, and their contract, integration, and failure tests.
- The repository also contains many databases, services, and deployment regions
  that this PR does not change. The changed command relationships are CLI/API to
  envelope to worker, plus the separate current Web UI/scheduler path through
  the direct adapter. Later work moves those legacy producers to the envelope.

Automated evidence at the pushed head:

- Contract and worker unit suites passed, 184 tests.
- CLI/API-to-worker integration suite passed, 23 scenarios.
- Generated clients are clean after regeneration.
- Retry and idempotency failure injection passed.

Observed manually at the pushed head in the repository root, on the disposable
local queue namespace `pr-202-local`, in no intended presentation order:

- `./bin/control command submit --queue pr-202-local --fixture fixtures/demo-command.json`
  returned an idempotency key and trace ID; that trace showed one worker
  execution and one stored result.
- `curl --fail --json @fixtures/demo-command.json http://127.0.0.1:8080/v1/commands`
  produced the same envelope fields and result shape as the CLI.
- `./bin/control command replay --queue pr-202-local "$idempotency_key"`
  returned the stored result without a second execution.
- `CONTROL_FAIL_ONCE=1 ./bin/control worker --queue pr-202-local` followed by
  the CLI submission produced one retry with the same trace and idempotency key.
- `./bin/control queue purge --queue pr-202-local` removed every command from
  that disposable namespace. After restarting the worker, a fresh CLI command
  completed. The purge command would be destructive against a shared queue.
- Cleanup stopped the local worker, ran
  `./bin/control queue delete --queue pr-202-local`, and ran
  `./bin/control fixtures delete-tenant --tenant pr-202` to remove only the
  fixture tenant's local rows.
