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

- [Hindsight local stack](docs/HINDSIGHT.md): configure and operate the
  launchd-managed local Hindsight API and control-plane UI.
