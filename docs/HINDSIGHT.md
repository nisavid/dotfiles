# Hindsight Local Stack

This repository manages the local Hindsight API, control-plane UI, launchd
supervisor, and client connection files. Run the service as the login user,
not as root.

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
- `~/.local/bin/hindsight-embed-service` and its supervisor/helpers
- `~/.hindsight/claude-code.json`, `~/.hindsight/codex.json`, and
  `~/.hindsight/cursor.json`

`hindsight-embed-service install` validates the rendered files, requires the
configured profile to exist, retires the legacy service label when present,
loads the LaunchAgent, and waits for the control service, API, and UI to become
healthy. It prints each bounded wait as it proceeds. The LaunchAgent starts the
stack again at each login and reconciles the API and UI if either stops.

## Recover An Incomplete Profile

If a profile was created with `configure --env`, rerun the interactive
`configure` command above for that profile, set `HINDSIGHT_BANK_ID` afterward,
then run `chezmoi apply` and `hindsight-embed-service install`. This refreshes
the profile's provider configuration without putting credentials in Git.

## Everyday Operation

```zsh
hindsight-embed-service status
hindsight-embed-service auth-refresh
hindsight-embed-service start
hindsight-embed-service stop
hindsight-embed-service logs
```

Use `status` after installation or a reboot. It reports the LaunchAgent, the
configured profile, and each stack component. `start` reloads or restarts the
LaunchAgent; `stop` unloads it and stops the control service, API, and UI.

Use `auth-refresh` when the Codex OAuth credentials used by Hindsight expire.
It reads `CODEX_HOME` from the configured Hindsight profile, runs the
interactive Codex login there, verifies the new login, and restarts the managed
stack so the daemon loads the refreshed credentials. A failed or cancelled
login leaves the running stack unchanged.

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

The client JSON files use the same API URL and bank as `hindsight.toml`.

## Boundaries

Keep provider credentials, profile environment files, control tokens, logs,
archives, and generated plugin state out of Git. The dotfiles source only owns
the non-secret desired service settings and client connection configuration.

`hindsight-embed-single-bank-cleanup` is a separate, destructive migration
runbook. It is not part of normal installation; begin with its default dry run
and use `--apply` only after reviewing the archive and migration plan.
