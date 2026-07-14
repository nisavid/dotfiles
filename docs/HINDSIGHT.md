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
control service, API, and UI if any component stops.

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
hindsight-embed-service start
hindsight-embed-service stop
hindsight-embed-service logs
```

Use `status` after installation or a reboot. It reports the LaunchAgent, broker
socket, configured profile endpoint, and each stack component. `start` reloads
or restarts the LaunchAgent; `stop` unloads it and performs a bounded stop of
the broker, control service, API, and UI.

## Configuration Changes

Edit [`home/.chezmoidata/hindsight.toml`](../home/.chezmoidata/hindsight.toml)
to change the profile, bank, ports, UI host, or autostart policy. For a profile
or bank change, follow the first-time setup flow so the profile exists before
the new service configuration is applied. For other changes, apply and restart
the managed stack:

```zsh
chezmoi apply
hindsight-embed-service start
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

`hindsight-embed-single-bank-cleanup` is a separate, destructive migration
runbook. It is not part of normal installation; begin with its default dry run
and use `--apply` only after reviewing the archive and migration plan.
