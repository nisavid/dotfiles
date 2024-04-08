#!/bin/sh

# Restore the ACLs of any chezmoi-managed filesystem nodes that have permissions
# settings that cannot be expressed in chezmoi's source state attributes.
#
# See the accompanying save script for more information.
#
# This script restores the saved permissions after `chezmoi apply` changes them
# during its update step.

ACL_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/chezmoi/acl"

if [ -f "$ACL_FILE" ] && [ -s "$ACL_FILE" ]; then
  echo "Restoring original permissions for the following paths:" >&2
  grep '^# file: ' "$ACL_FILE" | cut -d' ' -f3- >&2

  cd "$HOME" || exit 1
  setfacl --restore="$ACL_FILE" || exit 1
fi

rm -f "$ACL_FILE"
