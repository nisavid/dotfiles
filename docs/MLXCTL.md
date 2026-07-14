# mlxctl deployment

This repository owns the personal macOS deployment layer for the MLX service
manager in `nisavid/systools`: the `mlxd` LaunchAgent, deployment values, and
local-source install hook. The service manager implementation remains in the
`systools` repository.

## First-time setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and clone
`nisavid/systools` at `~/src/nisavid/systools`. The install source is its
`tools/mlxctl` subproject at `~/src/nisavid/systools/tools/mlxctl`. Review the
deployment values in [`home/.chezmoidata/mlxd.toml`](../home/.chezmoidata/mlxd.toml),
then apply the dotfiles:

```zsh
chezmoi apply
```

On macOS, chezmoi then:

- renders and registers `~/Library/LaunchAgents/io.nisavid.mlxd.plist`
  without starting it;
- renders `~/.config/mlxd/config.toml` with the personal server and model
  registry;
- creates `~/.config/mlxd`, `~/.local/state/mlxd`, and
  `~/Library/Logs/mlxd` with mode `0700`; and
- installs the local `tools/mlxctl` project with `uv tool install --force`,
  which provides `~/.local/bin/mlxctl` and `~/.local/bin/mlxd`.

The install hook runs after every apply so the installed tool follows the local
source checkout. Until that checkout contains an installable `pyproject.toml`,
the hook creates the deployment directories, reports that installation is
pending, removes any inactive stale LaunchAgent registration, and exits
successfully. It refuses to update the tool environment while the supervisor is
running.

## Disabled by default

The LaunchAgent is registered but inactive. Its `RunAtLoad` and `KeepAlive`
values are both false, so bootstrap does not start it and launchd does not
restart it automatically. Confirm registration without starting the service:

```zsh
launchctl print gui/$(id -u)/io.nisavid.mlxd
```

Start and stop configured inference servers through the CLI. When the control
socket is absent, `mlxctl start` kickstarts the registered supervisor:

```zsh
mlxctl status
mlxctl start <server>
mlxctl stop <server>
```

Remove the registration only when uninstalling the deployment:

```zsh
launchctl bootout gui/$(id -u)/io.nisavid.mlxd
```

## Managed paths

The plist invokes `~/.local/bin/mlxd` and sets:

- `PATH`, including `~/.local/bin`;
- `MLXD_CONFIG_DIR=~/.config/mlxd`;
- `MLXD_STATE_DIR=~/.local/state/mlxd`; and
- `MLXD_LOG_DIR=~/Library/Logs/mlxd`.

Supervisor stdout and stderr both append to `~/Library/Logs/mlxd/mlxd.log`.
The personal config defines a single `mlx_lm` proxy endpoint named `mlx` on
port 8765. It selects `mlx-community/Llama-3.2-3B-Instruct-4bit` through the
`llama-3b` alias and also registers
`mlx-community/Qwen2.5-7B-Instruct-4bit` as `qwen-7b`. Metrics are retained for
seven days. Daemon timeouts, metrics cadence, and the loopback host inherit the
v1 defaults. Keep model weights, API keys, runtime state, databases, and logs
out of Git.

## Other operating systems

The LaunchAgent and install hook render only on macOS. The checked-in
chezmoidata values are inert on other operating systems.
