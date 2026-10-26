# 🏠 dotfiles

My [dotfiles], managed by [chezmoi].

[dotfiles]: https://dotfiles.github.io
[chezmoi]: https://chezmoi.io

This incorporates my other configuration repositories by reference as
[chezmoi externals]:

[chezmoi externals]: https://chezmoi.io/user-guide/include-files-from-elsewhere

- [astronvim-config](https://github.com/nisavid/astronvim-config)

- [zsh-config](https://github.com/nisavid/zsh-config)

Zsh startup is installed from a commit-addressed archive with a SHA-256 pin in
`home/.chezmoiexternals/zsh-config.toml`. To update it, review the upstream
revision, verify the archive, and change its full commit and checksum together
in a reviewed dotfiles change. Refreshing externals cannot advance the revision
or accept changed archive bytes.

Applying the archive installs the paths it supplies from the reviewed contents
and preserves additional host-local profiles and runtime state outside those
paths in `~/.config/zsh`. The no-tracking hook retires the legacy
`zshrc.d/no-tracking.local.zsh` link when the modern profile is available.
Existing Git metadata is also retained to avoid discarding local work, but
chezmoi no longer pulls that checkout. Use the dotfiles pin to update managed
startup code; direct Git pulls or a host-defined `ZDOTDIR_ORIGIN` bypass this
deployment policy. This pin controls acquisition, not subsequent local edits or
separately downloaded Zsh plugins.

## 🛠️ Installation

#### [Install chezmoi](https://chezmoi.io/install)

#### Initialize chezmoi

```shell
chezmoi init https://github.com/nisavid/dotfiles
```

#### Apply dotfiles

```shell
chezmoi apply
```

## Services

- [Proton Drive](docs/PROTON_DRIVE.md): read-only Dolphin access during a
  Plasma session, with explicit activation and start, status, and stop controls.
- [Hindsight](docs/HINDSIGHT.md): retain reusable templates and a reviewed
  release pin, with no active consumer binding.

## Optional Codex quota safeguard

The [quota safeguard adapter](docs/CODEX_QUOTA_SAFEGUARD.md) installs a reviewed
`nisavid/agents` revision on Linux when explicitly selected. It is disabled by
default and never activates the watcher or MCP companion during chezmoi apply.
