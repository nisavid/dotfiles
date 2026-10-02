# 🏠 dotfiles

My [dotfiles], managed by [chezmoi].

[dotfiles]: https://dotfiles.github.io
[chezmoi]: https://chezmoi.io

This incorporates my other configuration repositories by reference as
[chezmoi externals]:

[chezmoi externals]: https://chezmoi.io/user-guide/include-files-from-elsewhere

- [astronvim-config](https://github.com/nisavid/astronvim-config)

- [zsh-config](https://github.com/nisavid/zsh-config)

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

- [Hindsight](docs/HINDSIGHT.md): retain reusable templates and a reviewed
  release pin, with no active consumer binding.

## Optional Codex quota safeguard

The [quota safeguard adapter](docs/CODEX_QUOTA_SAFEGUARD.md) installs a reviewed
`nisavid/agents` revision on Linux when explicitly selected. It is disabled by
default and never activates the watcher or MCP companion during chezmoi apply.
