# Proton Drive in Dolphin

`proton-drive-desktop` provides read-only access to Proton Drive during a
Plasma session. The launcher checks that the cloud mount is ready before
opening Dolphin. File contents are fetched on demand.

The maintained source requires host qualification before activation. Its
synthetic tests do not establish actual login, logout, wallet, or FUSE
behavior. The official Proton Drive CLI and unattended Hindsight backups have
separate credential and recovery procedures.

## Prerequisites

Use Linux with Plasma, systemd user services, Dolphin, rclone 1.75.1, the
distribution FUSE helper, KWallet's Secret Service, and the credential client
at `/usr/bin/secret-tool`. Confirm that the required client is executable:

```sh
test -x /usr/bin/secret-tool
```

This preflight checks only the client file. KWallet and Secret Service
readiness remain part of live qualification. The Plasma session must already
be running; the command does not start a desktop session.

Enrollment must already have produced the encrypted `proton-dolphin` remote
in `$XDG_CONFIG_HOME/rclone/proton-drive.conf` (normally
`~/.config/rclone/proton-drive.conf`) and its existing KWallet encryption-key
entry. The integration consumes that binding; it does not enroll an account.
Keep the configuration in place so rclone can update its session tokens.

The mount is `$XDG_DATA_HOME/proton-drive-desktop/files`, normally
`~/.local/share/proton-drive-desktop/files`. The user service and invoking
shell must agree on the XDG directories. Custom values must be absolute;
paths containing spaces are supported. Leave the mount directory empty and
reserve it for this service.

The helper records one XDG binding for the session in its private runtime
directory. Public controls and service entrypoints then use that same binding,
even if their inherited environments differ. Empty `XDG_CONFIG_HOME` or
`XDG_DATA_HOME` values select the standard defaults.

### Persist an already chosen custom XDG layout

Default-path users do not need this procedure. It is only for an existing,
already chosen custom layout; it does not migrate the desktop or credentials,
create the encrypted remote, or change the payload's install locations. The
persistent XDG environment also affects other newly launched desktop
processes, so choose that layout before using this procedure.

1. Before changing the environment, keep `proton-drive-desktop.service`
   disabled. If it was started manually, run `proton-drive-desktop stop` and
   confirm it stopped. If files are busy, close them and retry; do not force an
   unmount.
2. Create `~/.config/environment.d/90-proton-drive-xdg.conf`. Use
   `<original-XDG_CONFIG_HOME>/environment.d/90-proton-drive-xdg.conf` instead
   only when the user manager already inherited an absolute `XDG_CONFIG_HOME`
   at its original startup. Setting `XDG_CONFIG_HOME` in this file does not
   relocate this bootstrap file. For the default bootstrap location, create
   its directory if needed:

   ```sh
   mkdir -p -- "$HOME/.config/environment.d"
   ```

   Then create the file and write the two already chosen absolute paths, for
   example:

   ```ini
   XDG_CONFIG_HOME="$HOME/.config custom"
   XDG_DATA_HOME="$HOME/.local/share custom"
   ```

   Environment files use `KEY=VALUE`, expand `$HOME`, and allow quoted values
   with spaces; do not use `export` or other shell statements. The encrypted
   remote must already be at
   `$XDG_CONFIG_HOME/rclone/proton-drive.conf` under the chosen configuration
   path.
3. With the unit still disabled and stopped, arrange a reboot after saving the
   file. This gives the next login an unambiguous fresh user manager and Plasma
   session, even when a lingering manager would survive logout. A user
   `daemon-reload` also reruns environment generators, but their output applies
   to newly launched services, not already-running processes or unrelated
   shells.
4. Before enabling the unit in that fresh session, print the invoking
   terminal's resolved paths:

   ```sh
   printf 'XDG_CONFIG_HOME=%s\nXDG_DATA_HOME=%s\n' \
     "${XDG_CONFIG_HOME:-$HOME/.config}" \
     "${XDG_DATA_HOME:-$HOME/.local/share}"
   ```

   Inspect only the matching manager values:

   ```sh
   systemctl --user show-environment | sed -n \
     -e '/^XDG_CONFIG_HOME=/p' -e '/^XDG_DATA_HOME=/p'
   ```

   Do not `eval` this output; systemd may shell-quote whitespace. Require the
   terminal result and manager result to each match the two intended absolute
   paths, rather than merely matching each other.
5. Apply the reviewed payload while the unit is still disabled and stopped.
   It remains installed at `~/.local/bin/proton-drive-desktop`,
   `~/.config/systemd/user/proton-drive-desktop.service`, and
   `~/.local/share/applications/proton-drive.desktop`; the environment file
   does not relocate those files. After that apply and before the first
   `start` or `enable`, run this block to make the chosen custom discovery
   directories point to the fixed managed unit and launcher:

   ```sh
   # proton-drive-custom-xdg-links: setup
   set -eu
   unit_source="$HOME/.config/systemd/user/proton-drive-desktop.service"
   launcher_source="$HOME/.local/share/applications/proton-drive.desktop"
   normalize_discovery_root() {
     selected_root=$1
     while [ "$selected_root" != / ] && [ "${selected_root%/}" != "$selected_root" ]; do
       selected_root=${selected_root%/}
     done
     printf '%s\n' "$selected_root"
   }
   config_discovery_root=$(normalize_discovery_root "${XDG_CONFIG_HOME:-$HOME/.config}")
   data_discovery_root=$(normalize_discovery_root "${XDG_DATA_HOME:-$HOME/.local/share}")
   unit_link="${config_discovery_root%/}/systemd/user/proton-drive-desktop.service"
   launcher_link="${data_discovery_root%/}/applications/proton-drive.desktop"

   for discovery_destination in "$unit_link" "$launcher_link"; do
     case "$discovery_destination" in
       /*) ;;
       *) printf '%s\n' 'custom XDG discovery path must be absolute' >&2; exit 1 ;;
     esac
   done
   test -x "$HOME/.local/bin/proton-drive-desktop"
   test -r "$HOME/.config/systemd/user/proton-drive-desktop.service"
   test -r "$HOME/.local/share/applications/proton-drive.desktop"

   check_link() {
     source=$1
     destination=$2
     [ "$destination" = "$source" ] && return 0
     if [ -L "$destination" ]; then
       [ "$(readlink -- "$destination")" = "$source" ] || {
         printf 'refusing conflicting discovery link: %s\n' "$destination" >&2
         return 1
       }
     elif [ -e "$destination" ]; then
       printf 'refusing existing discovery destination: %s\n' "$destination" >&2
       return 1
     fi
   }
   check_link "$unit_source" "$unit_link"
   check_link "$launcher_source" "$launcher_link"

   mkdir -p -- "${unit_link%/*}" "${launcher_link%/*}"
   [ "$unit_link" = "$unit_source" ] || [ -L "$unit_link" ] ||
     ln -s -- "$unit_source" "$unit_link"
   [ "$launcher_link" = "$launcher_source" ] || [ -L "$launcher_link" ] ||
     ln -s -- "$launcher_source" "$launcher_link"
   cmp -s -- "$unit_source" "$unit_link"
   cmp -s -- "$launcher_source" "$launcher_link"
   ```

   Repeating the block reuses only those exact links. Other files and links
   are reported and preserved. Updates to the managed sources appear through
   the links; run `systemctl --user daemon-reload` after a unit update. Then
   require systemd and the chosen desktop data layout to discover the reviewed
   bytes:

   ```sh
   systemctl --user cat proton-drive-desktop.service >/dev/null
   test -r "${XDG_DATA_HOME:-$HOME/.local/share}/applications/proton-drive.desktop"
   ```

   If the intended manager values, unit, or launcher cannot be established,
   keep automatic startup disabled and report the gap.
6. Complete the manual checks below before enabling the unit. The later live
   qualification must use another fresh manager and Plasma session, let the
   enabled unit start automatically before any `proton-drive-desktop start` or
   `open`, then verify that `status`, the encrypted configuration, and the
   mount all use the intended paths, including paths with spaces.

For deliberate disable or recovery, first disable the unit and complete the
normal safe stop. Then this block removes only the two exact links above. It
leaves the managed payloads, conflicting destinations, and unrelated data in
place:

```sh
# proton-drive-custom-xdg-links: remove
set -eu
unit_source="$HOME/.config/systemd/user/proton-drive-desktop.service"
launcher_source="$HOME/.local/share/applications/proton-drive.desktop"
normalize_discovery_root() {
  selected_root=$1
  while [ "$selected_root" != / ] && [ "${selected_root%/}" != "$selected_root" ]; do
    selected_root=${selected_root%/}
  done
  printf '%s\n' "$selected_root"
}
config_discovery_root=$(normalize_discovery_root "${XDG_CONFIG_HOME:-$HOME/.config}")
data_discovery_root=$(normalize_discovery_root "${XDG_DATA_HOME:-$HOME/.local/share}")
unit_link="${config_discovery_root%/}/systemd/user/proton-drive-desktop.service"
launcher_link="${data_discovery_root%/}/applications/proton-drive.desktop"

for discovery_destination in "$unit_link" "$launcher_link"; do
  case "$discovery_destination" in
    /*) ;;
    *) printf '%s\n' 'custom XDG discovery path must be absolute' >&2; exit 1 ;;
  esac
done

check_exact_link() {
  source=$1
  destination=$2
  [ "$destination" = "$source" ] && return 0
  if [ -L "$destination" ]; then
    [ "$(readlink -- "$destination")" = "$source" ] || {
      printf 'refusing conflicting discovery link: %s\n' "$destination" >&2
      return 1
    }
  elif [ -e "$destination" ]; then
    printf 'refusing existing discovery destination: %s\n' "$destination" >&2
    return 1
  fi
}
check_exact_link "$unit_source" "$unit_link"
check_exact_link "$launcher_source" "$launcher_link"
[ "$unit_link" = "$unit_source" ] || [ ! -L "$unit_link" ] || rm -- "$unit_link"
[ "$launcher_link" = "$launcher_source" ] ||
  [ ! -L "$launcher_link" ] || rm -- "$launcher_link"
```

## Install and qualify

Read this procedure before installing, activating, updating, or recovering
the desktop integration. Use the reviewed repository revision and retain the
results for that revision. Keep account values and file contents out of test
reports.

1. Apply only the command, user unit, and desktop entry from the reviewed
   source. Chezmoi installs those files without enabling or starting the unit.
2. Exclude the service data directory from Baloo indexing before starting
   the mount. Baloo requires an existing directory. Under the existing XDG
   data directory, create the dedicated parent below with mode `0700`; the
   service will create its `files` mountpoint when starting. If the parent
   already exists, verify it is the expected user-owned directory, rather
   than a symlink or unrelated data, before reusing it. Preserve other
   exclusions. With the same XDG environment used by the service:

   ```sh
   proton_desktop_root="${XDG_DATA_HOME:-$HOME/.local/share}/proton-drive-desktop"
   mkdir -m 0700 -- "$proton_desktop_root"
   balooctl6 config add excludeFolders "$proton_desktop_root"
   balooctl6 config list excludeFolders
   ```

   Confirm the intended absolute path is listed. This prevents intentional
   recursive indexing; browsing and previews can still fetch files.
3. Reload the user units with `systemctl --user daemon-reload`, then run
   `proton-drive-desktop start` and `proton-drive-desktop status`. Confirm
   readiness before opening Dolphin through `proton-drive-desktop open`.
4. Browse and open a known synthetic file, close it, and run
   `proton-drive-desktop stop`. Confirm a clean stop, repeat stop, and then
   start again. An unmount failure or unexpected contents must be resolved
   before continuing; preserve the affected directory and running work.
5. Qualify failures without exposing account data: startup unavailable,
   locked or unavailable wallet, wrong mount, and a busy mount during stop.
   The launcher must not open an ordinary local directory as cloud storage.
   A failed start must remain visible through `status`, without automatic
   service restarts.
6. Enable the qualified unit with
   `systemctl --user enable proton-drive-desktop.service`. Arrange a logout
   test when other work can tolerate it. Confirm the mount stops at logout
   and returns ready after the next Plasma login. A user manager that
   continues running after logout must not keep this desktop mount active.

Activation is complete only after the operator controls, failure paths,
logout, and subsequent login have been observed on the installed revision.
If any check fails, keep activation incomplete and repair the cause before
repeating the affected checks.

## Daily use

Use **Proton Drive (read-only)** in the application launcher, or run:

```sh
proton-drive-desktop open
proton-drive-desktop status
proton-drive-desktop stop
proton-drive-desktop start
```

`status` checks the service and mount without starting either or retrieving
credentials. If the graphical launcher does not open Dolphin, run `open` in
a terminal to see its fixed diagnostic and inspect `status`.

Once the mount is ready, add its folder to Dolphin Places if desired. A
Places entry is a shortcut to a directory: it does not start the service or
verify readiness. Use the application launcher after a manual stop or a
failed login start.

Uploads and changes are unavailable through this mount. There is no offline
pinning or continuous two-way synchronization. Use the separately qualified
official CLI for transfers.

## Recover or disable

When stop reports busy files, close applications using the mount and retry
`proton-drive-desktop stop`. Preserve a foreign mount, replacement symlink,
or unexpected local file; investigate before acting. Avoid forced or lazy
unmounting and recursive cleanup.

When a transient startup problem leaves the unit failed without a residual
mount, an explicit `start` retries it after the normal safety checks. An
explicit `stop` clears an already failed, unmounted unit and its owned empty
mountpoint. Neither command proceeds when a residual or foreign mount remains.

If authentication expires, stop and use a separately reviewed enrollment or
repair procedure. Stock rclone can attempt password login when session reuse
fails. This integration neither guarantees session-reuse-only behavior nor
restores an old encrypted configuration after failure.

To disable login startup, run
`systemctl --user disable proton-drive-desktop.service`, then use the normal
`stop` command and confirm it stopped. Disabling the unit alone does not
unmount it. Leave existing credentials and user data in place.

## Source and verification

- Command: `home/private_dot_local/bin/executable_proton-drive-desktop`
- Unit: `home/dot_config/systemd/user/proton-drive-desktop.service`
- Launcher: `home/private_dot_local/private_share/applications/proton-drive.desktop`
- Behavior and disposable-deployment tests:
  `python3 -m unittest tests.test_proton_drive_desktop tests.test_proton_drive_desktop_deployment`
- Platform bindings: `zsh tests/platform-portability.zsh`

These tests use synthetic files and mocked account/process boundaries.
Before publishing changes, also run the repository's privacy and diff checks
from `AGENTS.md`. Credential or service behavior changes require review of
the changed scope and new host qualification.

Baloo's [settings schema](https://github.com/KDE/baloo/blob/master/src/lib/baloosettings.kcfg)
defines folder exclusions. The installed `balooctl6 config` help describes
the operator commands above.
