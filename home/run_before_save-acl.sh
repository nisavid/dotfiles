#!/bin/sh

# Save the ACLs of any chezmoi-managed filesystem nodes that have permissions
# settings that cannot be expressed in chezmoi's source state attributes.
#
# Using its `private`, `readonly`, and `executable` attributes, chezmoi
# effectively supports declaring the following octal permission modes:
#
#   • For directories: 0755, 0700, 0555, 0500
#
#   • For regular files: 0755, 0700, 0644, 0600, 0555, 0500, 0444, 0400
#
# It has no support for declaring the more granular permissions afforded
# by file access control lists (ACLs).
#
# When `chezmoi add` encounters a node whose permissions cannot be expressed
# in its source state attributes, it effectively saves an incorrect permissions
# state for that node.  This can be problematic:
#
#   1. The correct permissions are not saved in the chezmoi source state,
#      so they are not declaratively managed by chezmoi in the same manner
#      as the permission modes that it supports.  If the target state deviates
#      from the desired permissions, `chezmoi diff` will not report this,
#      and `chezmoi apply` will not correct it.  On a newly configured system,
#      `chezmoi init` does not replicate the permissions on the original system.
#
#   2. Chezmoi applies those incorrectly stored permissions on a subsequent
#      `chezmoi apply`, even if the target state hasn't actually changed since
#      `chezmoi add` was run on it.  This can remove permissions that are
#      necessary for functionality and add permissions that open up security
#      vulnerabilities.
#
#   3. If the node has an ACL that includes an effective rights mask, then
#      `chezmoi apply` may silently change that mask.  Unlike its changes
#      to the traditional permission mode bits---which show up
#      in a `chezmoi diff`---it does not notify the user at any point
#      about this change.  To correct the mask, the user must know what the mask
#      was previously and manually restore it after each `chezmoi apply`.
#
#   4. There is no way to tell chezmoi to behave otherwise---neither globally
#      nor for a particular node.
#
# Whereas, in principle, declaratively managing dotfile permissions is useful,
# these limitations pose problems that are easy to miss and potentially
# introduce issues with functionality and security.  This script
# (and the accompanying restore script) implements a partial workaround
# for this conundrum.  It does not address the inability to fully replicate
# the permissions between chezmoi installations, but it does effectively prevent
# `chezmoi apply` from mangling the permissions on the original system.
# More precisely, it unmangles them at the end of each `chezmoi apply`.
#
# This script traverses all the chezmoi-managed filesystem nodes.  For any node
# that has an ACL or a permission mode that chezmoi doesn't support, it saves
# the permissions settings to a state file.  The accompanying restore script
# subsequently restores those saved permissions after `chezmoi apply` changes
# them during its update step.

ACL_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/chezmoi/acl"
mkdir -p "$(dirname "$ACL_FILE")"
: >"$ACL_FILE"

cd -- "$HOME" || exit 1

chezmoi managed | while read -r item; do
  [ -e "$item" ] || continue
  [ -L "$item" ] && continue
  [ -d "$item" ] || [ -f "$item" ] || continue

  save=0

  if [ "$(
    getfacl -- "$item" 2>/dev/null |
      grep -cvE '^$|^#|^(user|group|other)::'
  )" -ne 0 ]; then
    save=1
  else
    perms=$(stat -c %a "$item")
    if [ -d "$item" ]; then
      case $perms in
      755 | 700 | 555 | 500) ;;
      *)
        save=1
        ;;
      esac
    elif [ -f "$item" ]; then
      case $perms in
      644 | 600 | 444 | 755 | 700 | 555 | 500 | 400) ;;
      *)
        save=1
        ;;
      esac
    fi
  fi

  if [ "$save" -eq 1 ]; then
    getfacl -- "$item" >>"$ACL_FILE"
  fi
done
