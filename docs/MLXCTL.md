# mlxctl installation

These dotfiles may install `mlxctl` from an operator-configured local source.
`mlxctl` owns its daemon, runtimes, models, services, gateway, and client
integrations. Chezmoi does not configure or operate those resources.

## Install or update

Install `uv`, provide the configured source checkout, and apply the dotfiles:

```zsh
chezmoi apply
```

On supported systems, the after-install hook runs `uv tool install --force`
against the configured source. If the source or its `pyproject.toml` is absent,
the hook reports that installation was skipped and leaves the machine
unchanged. It fails when `uv` is unavailable or installation does not produce
the expected `mlxctl` entry point.

Verify the installation:

```zsh
mlxctl --help
```

Use `mlxctl` itself to configure runtime installation, models, services,
gateway behavior, and client integrations.

## Ownership boundary

Chezmoi owns only the local-source tool installation. It does not:

- render or register runtime services;
- create or write tool configuration, state, logs, runtimes, or model data;
- install model providers or download models; or
- select providers or write client integration settings.

Keep source locations, model weights, credentials, runtime state, databases,
and logs out of public Git content. Machine-specific source selection belongs
in encrypted configuration.

## Existing deployments

These dotfiles leave earlier runtime targets and data unmanaged. Before
configuring `mlxctl`, inspect and archive any deployment you intend to keep,
stop its services, and use the tool's supported migration or adoption
operations. Remove legacy targets only after the replacement is verified.

The local-source install hook is platform-gated. Its configuration is inert on
unsupported operating systems.
