# 🏠 dotfiles

My [dotfiles], managed by [chezmoi].

[dotfiles]: https://dotfiles.github.io
[chezmoi]: https://chezmoi.io

This incorporates my other configuration repositories by reference as
[chezmoi externals]:

[chezmoi externals]: https://chezmoi.io/user-guide/include-files-from-elsewhere

- [astronvim-config](https://github.com/nisavid/astronvim-config)

- [zsh-config](https://github.com/nisavid/zsh-config)

The Zsh checkout is installed by `run_before_install-zsh-config.zsh.tmpl`,
not a refreshing Git external. The full commit and SHA-256 in
`home/.chezmoidata/zsh-config.toml` bind its startup code to this repository.
The hook verifies a Git-generated tar archive before checking out that commit;
repeated applies do not pull the upstream default branch. It retains `.git`
and untracked local profiles, removes retired tracked files through Git, and
refuses tracked or staged local edits rather than overwriting them. An existing
checkout moves to a detached HEAD when the pin changes; its branches remain.
An already matching checkout keeps its current branch and file metadata.

To advance the pin, review the proposed upstream commit, then update both
values in a dotfiles change. Compute the digest in a clean upstream checkout
with `git -c tar.umask=0002 archive --format=tar FULL_COMMIT | shasum -a 256`.
This digest is for Git's tar output, not GitHub's generated `.tar.gz` download.
Run `python3 -m unittest tests.test_zsh_config_pin` and the deployment suites
before applying the change. Commit or otherwise preserve tracked local work
before applying; local development branches and untracked profiles are retained.

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
