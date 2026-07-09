# Hindsight Local Stack

This repository manages the local Hindsight API, control-plane UI, launchd
supervisor, and client connection files. Run the service as the login user,
not as root.

## First-Time Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) so
`~/.local/bin/uvx` is executable. Then choose a profile, bank, and API port.
Set the matching non-secret values in
[`home/.chezmoidata/hindsight.toml`](../home/.chezmoidata/hindsight.toml)
before applying the dotfiles.

```zsh
profile=YOUR_PROFILE
bank_id=YOUR_BANK_ID
api_port=YOUR_API_PORT

chezmoi apply

uvx hindsight-embed configure --profile "$profile" --port "$api_port" \
  --env "HINDSIGHT_BANK_ID=$bank_id"
uvx hindsight-embed profile set-active "$profile"

hindsight-embed-service install
hindsight-embed-service status
```

`configure` stores the provider credential in the local Hindsight profile. It
is an interactive, machine-local step and is not managed by chezmoi.

`chezmoi apply` renders these managed targets:

- `~/Library/LaunchAgents/com.hindsight.embed.stack.plist`
- `~/.local/bin/hindsight-embed-service` and its supervisor/helpers
- `~/.hindsight/claude-code.json`, `~/.hindsight/codex.json`, and
  `~/.hindsight/cursor.json`

`hindsight-embed-service install` validates the rendered files, retires the
legacy service label when present, loads the LaunchAgent, and waits for the
control service, API, and UI to become healthy. The LaunchAgent starts the
stack again at each login and reconciles the API and UI if either stops.

## Everyday Operation

```zsh
hindsight-embed-service status
hindsight-embed-service start
hindsight-embed-service stop
hindsight-embed-service logs
```

Use `status` after installation or a reboot. It reports the LaunchAgent and
each stack component. `start` reloads or restarts the LaunchAgent; `stop`
unloads it and stops the control service, API, and UI.

## Configuration Changes

Edit [`home/.chezmoidata/hindsight.toml`](../home/.chezmoidata/hindsight.toml)
to change the profile, bank, ports, UI host, or autostart policy. Apply the
rendered configuration and restart the managed stack:

```zsh
chezmoi apply
hindsight-embed-service start
hindsight-embed-service status
```

The profile and bank in `hindsight.toml` must match the profile created during
first-time setup. The client JSON files use the same API URL and bank.

## Boundaries

Keep provider credentials, profile environment files, control tokens, logs,
archives, and generated plugin state out of Git. The dotfiles source only owns
the non-secret desired service settings and client connection configuration.

`hindsight-embed-single-bank-cleanup` is a separate, destructive migration
runbook. It is not part of normal installation; begin with its default dry run
and use `--apply` only after reviewing the archive and migration plan.
