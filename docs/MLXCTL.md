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

On the `hatchery` host, the same hook also installs `mlx-optiq==0.2.15`,
downloads the pinned Qwen3.6 OptiQ snapshot, verifies its published KV config,
and configures the existing `systalyze` Hindsight profile. The snapshot is
large; confirm memory and disk capacity before the first apply on that host.

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
The existing `mlx_lm` Client Endpoint named `mlx` remains on port 8765. On
`hatchery`, the config additionally defines the `qwen36-optiq` Model Alias and
an `optiq` Server Definition at `http://127.0.0.1:8766`. It serves the pinned
`mlx-community/Qwen3.6-35B-A3B-OptiQ-4bit` snapshot with:

- model revision `70a3aa32c7feef511182bf16aa332f37e8d82014`;
- the repository's `kv_config.json`, verified as SHA-256
  `34846a2678e2d390454af58e9296859b730beaa3dc6974644262e2d07110edc5`;
- MTP enabled;
- a 32,768-token server context; and
- a deterministic default temperature of `0.0`.

Codex selects a host-scoped `mlx-optiq` Responses API provider at that Client
Endpoint. Codex does not expose a temperature setting in its current config
schema, so it inherits the deterministic server default. The Hindsight
`systalyze` profile uses its `lmstudio` OpenAI-compatible provider against the
same endpoint and sends task-specific temperatures: `0.0` for verification,
`0.1` for retain, `0.9` for reflect, and `0.0` for consolidation. Hindsight is
limited to one concurrent LLM request. Existing provider definitions and
credentials are not deleted.

Metrics are retained for seven days. Daemon timeouts, metrics cadence, and the
loopback host inherit the v1 defaults. Keep model weights, API keys, runtime
state, databases, and logs out of Git.

## Verify the OptiQ deployment

After applying on `hatchery`, restart Hindsight so its profile environment is
reloaded, then verify the managed service without exposing either endpoint:

```zsh
setopt PIPE_FAIL
optiq --version
mlxctl status optiq
mlxctl start optiq
mlxctl models optiq
curl --fail --show-error --silent http://127.0.0.1:8766/v1/models | jq .
mlxctl metrics optiq
mlxctl stop optiq
```

Inspect the active OptiQ process and confirm that its arguments contain both
`--kv-config` and `--mtp`. Exercise Codex with a representative engineering
request and Hindsight with retain, recall, and reflect requests before treating
the host as complete. Record startup time, token generation, memory pressure,
logs, and clean shutdown during that target-host verification.

## Other operating systems

The LaunchAgent and install hook render only on macOS. The checked-in
chezmoidata values are inert on other operating systems.
