# mlxctl installation

This repository installs the `mlxctl` project from a local `systools` checkout.
`mlxctl` owns its daemon, runtimes, models, services, gateway, and client
integrations. Chezmoi does not configure or operate those resources.

## Install or update mlxctl

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and clone
`nisavid/systools` at `~/src/nisavid/systools`. The install source is
`~/src/nisavid/systools/tools/mlxctl`.

Apply the dotfiles:

```zsh
chezmoi apply
```

On macOS, the after-install hook runs:

```zsh
uv tool install --force ~/src/nisavid/systools/tools/mlxctl
```

If the checkout or its `pyproject.toml` is absent, the hook reports that
installation was skipped and leaves the machine unchanged. It fails when `uv`
is unavailable or the install does not produce `~/.local/bin/mlxctl`.

Verify the installed entrypoint:

```zsh
mlxctl --help
```

Then use `mlxctl setup` or the guided TUI to configure the machine. Runtime
installation, model discovery and adoption, service lifecycle, gateway setup,
and Codex or Hindsight integration are all mlxctl operations.

## Migrate an earlier deployment

Earlier versions of these dotfiles managed an `io.nisavid.mlxd` LaunchAgent,
`~/.config/mlxd`, `~/.local/state/mlxd`, `~/Library/Logs/mlxd`, standalone
OptiQ installation, model downloads, and MLX client fields. These paths may
contain useful configuration, model weights, logs, or runtime evidence.

Chezmoi now leaves those legacy targets untouched and unmanaged. It does not
stop or remove the old LaunchAgent and does not delete, move, or rewrite any
legacy data. Before configuring mlxctl, inspect and archive the old deployment,
stop its running services, and use mlxctl's migration or adoption operations to
bring forward the resources you intend to keep. Remove obsolete legacy targets
only after the new deployment is verified.

## Ownership boundary

Chezmoi owns only the local-source tool installation. In particular, it does
not:

- render or register a LaunchAgent;
- create or write mlxctl or mlxd configuration, state, log, runtime, or model
  paths;
- install OptiQ or download Hugging Face models; or
- select a model provider or write MLX settings for Codex or Hindsight.

The source path is declared in
[`home/.chezmoidata/mlxctl.toml`](../home/.chezmoidata/mlxctl.toml). Keep model
weights, API keys, runtime state, databases, and logs out of Git.

## Other operating systems

The local-source install hook renders only on macOS. The checked-in source path
is inert on other operating systems.
