# Hindsight Local Stack

This repository manages the local Hindsight API, control-plane UI, inactive
memory broker, launchd supervisor, and client broker bindings. Run the service
as the login user, not as root.

## First-Time Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) so
`~/.local/bin/uvx` is executable. Choose a named profile, bank, and API port,
then set the matching non-secret values in
[`home/.chezmoidata/hindsight.toml`](../home/.chezmoidata/hindsight.toml):

```toml
[hindsight]
profile = "YOUR_PROFILE"
profiles = ["YOUR_PROFILE"]
bank = "YOUR_BANK_ID"
apiPort = YOUR_API_PORT
```

Replace every placeholder before continuing. Shell variables alone do not
change the managed service configuration. Derive the setup values from the
chezmoi source so the profile setup and rendered LaunchAgent agree:

```zsh
profile="$(chezmoi execute-template '{{ .hindsight.profile }}')"
bank_id="$(chezmoi execute-template '{{ .hindsight.bank }}')"
api_port="$(chezmoi execute-template '{{ .hindsight.apiPort }}')"

uvx hindsight-embed configure --profile "$profile" --port "$api_port"
uvx hindsight-embed profile set-env "$profile" HINDSIGHT_BANK_ID "$bank_id"

chezmoi apply
hindsight-embed-service install
uvx hindsight-embed profile set-active "$profile"
hindsight-embed-service status
```

`configure` is intentionally run without `--env`: supplying `--env` selects
Hindsight's non-interactive path and bypasses provider setup. The CLI currently
labels interactive `configure` as deprecated, but it remains the named-profile
path that keeps credentials out of process arguments. Do not replace it with
`profile create --env` when supplying credentials.

`chezmoi apply` renders these managed targets:

- `~/Library/LaunchAgents/com.hindsight.embed.stack.plist`
- `~/.local/bin/hindsight-embed-service`, `~/.local/bin/hindsight-memory`, and
  their supervisor/helpers
- `~/.hindsight/claude-code.json`, `~/.hindsight/codex.json`, and
  `~/.hindsight/cursor.json`

`hindsight-embed-service install` validates the rendered files, requires the
configured profile to exist, retires the legacy service label when present,
loads the LaunchAgent, and waits for the memory broker, control service, API,
and UI to become healthy. It prints each bounded wait as it proceeds. The
LaunchAgent starts the stack again at each login and reconciles the broker,
control service, every profile in `HINDSIGHT_EMBED_FLEET_PROFILES`, and each declared local
provider sidecar if a desired-running component stops. An API or UI stopped in
the Embed Control Center remains stopped for the current login session; starting it in
the Control Center restores crash recovery. An explicit service start or
restart and a new login restore the configured autostart policy. The first
profile remains the primary profile used by the existing single-profile status
lines.

The broker starts in inactive mode on
`~/.local/state/hindsight-memory/broker.sock`. It owns its signing material in
that private state directory, installs no data-plane route, and denies session
minting. Applying these dotfiles does not activate any harness or authorize a
memory write.

## Recover An Incomplete Profile

If a profile was created with `configure --env`, rerun the interactive
`configure` command above for that profile, set `HINDSIGHT_BANK_ID` afterward,
then run `chezmoi apply` and `hindsight-embed-service install`. This refreshes
the profile's provider configuration without putting credentials in Git.

## Everyday Operation

```zsh
hindsight-embed-service status
hindsight-embed-service status --profile "$profile"
hindsight-embed-service start
hindsight-embed-service restart
hindsight-embed-service stop
hindsight-embed-service logs
```

Use `status` after installation or a reboot. It reports the LaunchAgent, broker
socket, fleet health, stable profile slots, endpoint readiness, and sidecar
readiness. `status --profile NAME` selects one enabled profile. `start` reloads
or starts the LaunchAgent. `restart` performs a validated clean stop/start so
profile changes replace the running daemon. `stop` unloads the LaunchAgent and
performs a bounded stop of the broker, control service, every enabled API/UI
pair, and declared sidecars.

The managed Control Center adds `OpenAI Codex (subscription)` and `Claude Code
(subscription)` to Hindsight Embed's provider catalog. These provider entries
use the corresponding local OAuth subscription state and do not require an API
key in the profile.

Each optional sidecar is declared under
`~/.hindsight/profiles/PROFILE.sidecars/NAME/`. A declaration contains either
`port` or `port-base`, may contain `health-path`, and may provide executable
`start`, `status`, and `stop` hooks. Slot-derived ports and explicit overrides
must be unique across the fleet.

## Configuration Changes

Edit [`home/.chezmoidata/hindsight.toml`](../home/.chezmoidata/hindsight.toml)
to change the profile, bank, ports, UI host, or autostart policy. For a profile
or bank change, follow the first-time setup flow so the profile exists before
the new service configuration is applied. For other changes, apply and restart
the managed stack:

```zsh
chezmoi apply
hindsight-embed-service restart
hindsight-embed-service status
```

The client JSON files contain only the private broker socket and adapter
identity. They remain `active: false`; direct API URLs, bank destinations, and
credentials are not rendered into harness configuration.

## Boundaries

Keep provider credentials, profile environment files, control tokens, logs,
archives, and generated plugin state out of Git. The dotfiles source only owns
the non-secret desired service settings and client connection configuration.

Broker health is not activation approval. Enabling a harness requires a
separate digest-bound activation plan with unchanged inventory, policy,
artifact, endpoint, and owned-key pre-state plus a healthy broker/profile and
adapter self-test. Migration mutation additionally requires the matching
two-part completion gate and an independently approved immutable mutation plan.
On activation failure, restore the recorded harness-owned values and leave the
adapter disabled. On migration failure, keep profile writes frozen and use the
verified rollback artifacts named by the approved plan.

The completion marker is
`MIGRATION_ARTIFACT_DIR/distillation-complete.marker` with exactly
`run=RUN_ID` and `artifact=SHA256` lines. The proposal log must contain a
`## Migration complete` section with the same two lines. `hindsight-memory
apply` rereads both trusted regular files immediately before mutation, requires
the approved plan digest, and resolves the data-plane token only from the named
environment variable. Trusted gate and restore-evidence files and every
directory ancestor must be owned by the current user or root. Files must have
one hard link and must not be group or world writable; paths must not descend
through a non-sticky writable directory. The gate SHA-256 identifies the
completed migration package, independently of the desired-state inventory
digest.

A mutation action binds distinct source and target bank references, the
completion-gate artifact digest, its `--migration-archive` digest, and the
canonical digest of its disposable restore-evidence record. The migration
archive and evidence bindings must be distinct from the rollback bindings.
The evidence record contains only `schema_version`, the archive's
`artifact_digest`, and the digest of an independently reviewed disposable-
restore verification receipt. Apply copies verified archive bytes into a
private mode-`0400` snapshot below a mode-`0700` directory, passes only that
snapshot to the Hindsight 0.8.4 vector `hindsight-admin import-bank --archive
ARCHIVE --target-bank BANK`, and removes it after the command. Snapshot creation
rejects archives larger than 8 GiB. Archive digests remain out-of-band approval
inputs and are not passed to the CLI.

The plan separately binds the `--rollback-archive` digest and its
restore-evidence record digest. Apply runs `hindsight-admin backup ARCHIVE
--schema public`, verifies the resulting archive digest before mutation, and
uses a fresh verified private snapshot with `hindsight-admin restore ARCHIVE
--schema public --yes` if a postcondition fails.

`hindsight-embed-single-bank-cleanup` is a separate, destructive migration
runbook. It is not part of normal installation; begin with its default dry run
and use `--apply` only after reviewing the archive and migration plan.
