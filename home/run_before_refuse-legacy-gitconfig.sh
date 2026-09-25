#!/bin/sh

# Refuse to apply while ~/.gitconfig exists.
#
# Git reads ~/.gitconfig after ~/.config/git/config, so any value there
# overrides the managed Git configuration, and a catch-all setting such as
# `credential.helper = store` still applies to hosts the managed file scopes
# to other helpers. `git config --global` also writes to ~/.gitconfig whenever
# it exists, so tools keep adding to it unnoticed.

legacy="${CHEZMOI_DEST_DIR:-$HOME}/.gitconfig"
managed="${CHEZMOI_DEST_DIR:-$HOME}/.config/git/config"

if [ -e "$legacy" ] || [ -L "$legacy" ]; then
  cat >&2 <<EOF
refuse-legacy-gitconfig: $legacy exists.
Git reads it after ~/.config/git/config, so its values override the managed
Git configuration. Move anything worth keeping into the chezmoi source, or
into ~/.config/git/config.local for machine-local settings, then remove
$legacy and apply again.
EOF
  # CodeRabbit reads its ID with plain `git config --global`, which skips
  # includes, so config.local can't hold it; the managed template carries it
  # forward from the deployed ~/.config/git/config instead.
  if git config --file "$legacy" coderabbit.machineId >/dev/null 2>&1; then
    cat >&2 <<EOF

It holds CodeRabbit's machine ID, which CodeRabbit can't read from
config.local. Copy it into the managed file before removing $legacy:

  git config --file "$managed" coderabbit.machineId "\$(git config --file "$legacy" coderabbit.machineId)"
EOF
  fi
  exit 1
fi
