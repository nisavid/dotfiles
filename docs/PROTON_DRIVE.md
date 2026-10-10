# Proton Drive in Dolphin

`proton-drive-desktop` provides read-only access to Proton Drive during a
Plasma session. The launcher checks that the cloud mount is ready before
opening Dolphin. File contents are fetched on demand.

The maintained source requires host qualification before activation. Its
synthetic tests do not establish actual login, logout, wallet, or FUSE
behavior. The official Proton Drive CLI and unattended Hindsight backups have
separate credential and recovery procedures.

Startup gives rclone the exact managed mountpoint as a supported ordinary-user
pathname. Immediately before executing rclone, the final descriptor-backed
inspection in `_mount` safely opens the managed parent and leaf, rejects a
mount or replacement, checks the recorded directory identity and nonce, and
requires the leaf to be empty. Reserve the managed parent and mountpoint for
this integration throughout startup, the mounted session, and completed
shutdown. Other programs must not rename or replace either directory, mount
over the managed path, or independently unmount it during that interval. Use
the provided controls to stop the mount; normal Dolphin browsing and opening
files are unaffected. Repeated checks and held close-on-exec descriptors do
not enforce this reservation or prove unconditional pathname identity.

Before preparation and again during the final launch inspection, the helper
opens every lexical directory from `/` through the managed parent without
following symlinks. Every component must be a directory with no group or
other write bit; the data directory and managed parent must also belong to the
user. There is no sticky-directory exception: a custom layout below `/tmp` is
rejected even when its private descendants use mode `0700`.

Readiness proves that exactly one constrained read-only `fuse.rclone` mount at
the reserved pathname carries this launch's random source tag and recorded
mount ID. It does not identify the directory hidden beneath that mount. A
change detected before launch, during a later status check, or during cleanup
fails closed and is preserved. A concurrent change during the reserved
interval is unsupported: stock rclone/FUSE mounts and unmounts by pathname,
so a replacement may be mounted over or unmounted despite a preceding identity
check. This contract also applies at logout and direct service shutdown.
Activation therefore still requires an ordinary-user live check
with rclone 1.75.1 and the distribution FUSE helper; synthetic exec mocks do
not establish that FUSE works.

## Prerequisites

Use Linux with Plasma, systemd user services, Dolphin, rclone 1.75.1, the
distribution FUSE helper, KWallet's Secret Service, and the credential client
at `/usr/bin/secret-tool`. Before authentication or mounting, inspect the
installed client and confirm that the credential client is executable:

```sh
/usr/bin/rclone version
test -x /usr/bin/secret-tool
```

The first version line must be `rclone v1.75.1`. Stop on a different version
or a failed command; qualify that client revision before proceeding. Confirm
the executable belongs to the expected distribution package and has not been
locally replaced. On Arch, use `pacman -Qo /usr/bin/rclone` and
`pacman -Qkk rclone`, and retain the signed package's version and provenance
with the qualification results. Resolve unexpected ownership or file changes
before starting the service.

These checks establish the installed prerequisites. KWallet and Secret
Service readiness remain part of live qualification. The Plasma session must
already be running; the command does not start a desktop session.

Enrollment must already have produced the encrypted `proton-dolphin` remote
in `$XDG_CONFIG_HOME/rclone/proton-drive.conf` (normally
`~/.config/rclone/proton-drive.conf`) and its existing KWallet encryption-key
entry. The integration consumes that binding; it does not enroll an account.
Keep the configuration in place so rclone can update its session tokens.

The configuration must be a regular, user-owned mode-0600 file. Its parent
directory must also belong to the user. Every directory from `/` through that
parent must be free of symlinks and group or other write permissions. Custom
configuration paths below `/tmp` are unsupported, including private descendants
of that sticky directory.

The KWallet encryption-key entry must have the Secret Service attributes
`application=rclone`, `purpose=proton-drive-config`, and `config-id` equal to
the lowercase SHA-256 of the UTF-8 absolute configuration path. Moving the
configuration changes that binding. Use `proton-drive-desktop start` to check
that the existing entry can unlock the configuration: `ready` confirms the
binding works without displaying the key. If it fails, resolve the binding
through the separate enrollment or repair procedure before enabling startup.

For each lookup, the helper requires `org.freedesktop.secrets` and
`org.kde.ksecretd` to have the same unique D-Bus owner before invoking
`secret-tool`, then requires both names to retain that owner before releasing
the captured value to rclone. A provider restart has a different unique owner
and is rejected. These two samples do not bind `secret-tool` directly to the
unique owner and do not close an owner-change-and-return race between samples;
actual provider behavior remains part of live qualification.

Rclone's password command includes the current launch's nonsecret source tag.
The credential endpoint requires that tag to match the prepared or verified
ownership record and confirms that standard output is a pipe before any Secret
Service lookup. Direct calls, terminal output, regular-file output, stale tags,
and mismatched launch state fail with a fixed diagnostic. This binding prevents
accidental misuse; it does not resist a hostile same-UID process that can read
and reproduce the private state.

The helper starts `secret-tool` without a secret in its arguments or
environment, discards its diagnostics, and reads through a pipe under a
10-second deadline. It reads no more than a 4,096-byte key plus its permitted
line ending and one overflow byte. Oversized, continuous, failed, or timed-out
producers are terminated and reaped before the helper reports the fixed
credential error. No temporary credential file is used.

The mount is `$XDG_DATA_HOME/proton-drive-desktop/files`, normally
`~/.local/share/proton-drive-desktop/files`. The user service and invoking
shell must agree on the XDG directories. Custom values must be absolute;
paths containing spaces are supported. Leave the mount directory empty and
reserve it for this service. After a clean stop, the helper retains that empty
underlying directory; it removes only its private identity xattr and runtime
ownership records.

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
   run the effective-unit qualification below and require the chosen desktop
   data layout to expose the reviewed launcher bytes:

   ```sh
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

Run the block with the same `XDG_CONFIG_HOME` and `XDG_DATA_HOME` values used
during setup. If the layout has changed, restore those original values in a
subshell and run the block there; current values would address different
links. Remove the original links before changing or removing the persistent
environment file.

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

### Qualify the effective loaded unit

Run this block from the reviewed repository root after `systemctl --user
daemon-reload` and before the first `start` or `enable`. Run it for both the
standard layout and the custom-XDG discovery-link layout. It refuses a unit
loaded from any other fragment, installed-byte drift, and every drop-in; keep
activation disabled if it fails.

```sh
# proton-drive-effective-unit: qualify
set -eu
reviewed_unit=home/dot_config/systemd/user/proton-drive-desktop.service
installed_unit="$HOME/.config/systemd/user/proton-drive-desktop.service"

test -f "$reviewed_unit"
test -f "$installed_unit"
cmp -s -- "$reviewed_unit" "$installed_unit" || {
  printf '%s\n' 'installed Proton Drive unit differs from reviewed source' >&2
  exit 1
}

effective_fragment=$(systemctl --user show proton-drive-desktop.service \
  --property=FragmentPath --value)
effective_drop_ins=$(systemctl --user show proton-drive-desktop.service \
  --property=DropInPaths --value)
test -n "$effective_fragment" || {
  printf '%s\n' 'Proton Drive unit has no loaded fragment' >&2
  exit 1
}
test "$(readlink -f -- "$effective_fragment")" = \
  "$(readlink -f -- "$installed_unit")" || {
  printf '%s\n' 'Proton Drive unit is loaded from an unexpected fragment' >&2
  exit 1
}
cmp -s -- "$reviewed_unit" "$effective_fragment" || {
  printf '%s\n' 'loaded Proton Drive unit differs from reviewed source' >&2
  exit 1
}
test -z "$effective_drop_ins" || {
  printf '%s\n' 'unreviewed Proton Drive unit drop-ins are loaded' >&2
  exit 1
}
```

## Install and qualify

Read this procedure before installing, activating, updating, or recovering
the desktop integration. Use the reviewed repository revision and retain the
results for that revision. Keep account values and file contents out of test
reports.

1. Complete the prerequisite checks above. For an update, use the installed
   command to stop the existing mount cleanly before replacing its files.
   Apply only the command, user unit, and desktop entry from the reviewed
   source. Chezmoi installs those files without enabling or starting the unit.
   The desktop entry renders an absolute command path so it does not depend
   on Plasma inheriting the shell's `PATH`.
2. Exclude the service data directory from Baloo indexing before starting
   the mount. Baloo requires an existing directory. Under the existing XDG
   data directory, create the dedicated parent below with mode `0700`; the
   service will create its `files` mountpoint on the first start and retain the
   empty reserved mountpoint after clean stops. If the parent
   already exists, verify it is the expected user-owned directory, rather
   than a symlink or unrelated data, before reusing it. Preserve other
   exclusions. With the same XDG environment used by the service:

   ```sh
   # proton-drive-baloo: setup
   set -eu

   xdg_data_root=${XDG_DATA_HOME:-"$HOME/.local/share"}
   case "$xdg_data_root" in
     /*) ;;
     *) printf '%s\n' 'XDG_DATA_HOME must be an absolute path' >&2; exit 1 ;;
   esac
   while [ "$xdg_data_root" != "/" ] && [ "${xdg_data_root%/}" != "$xdg_data_root" ]; do
     xdg_data_root=${xdg_data_root%/}
   done
   if [ "$xdg_data_root" = "/" ]; then
     proton_desktop_root=/proton-drive-desktop
   else
     proton_desktop_root=$xdg_data_root/proton-drive-desktop
   fi

   if [ ! -e "$proton_desktop_root" ] && [ ! -L "$proton_desktop_root" ]; then
     mkdir -m 0700 -- "$proton_desktop_root"
   fi
   if [ -L "$proton_desktop_root" ] || [ ! -d "$proton_desktop_root" ]; then
     printf '%s\n' 'managed Baloo parent is not a directory or is a symlink' >&2
     exit 1
   fi
   if ! proton_desktop_identity=$(stat -Lc '%u %a' -- "$proton_desktop_root"); then
     printf '%s\n' 'managed Baloo parent identity is unavailable' >&2
     exit 1
   fi
   proton_desktop_owner=${proton_desktop_identity%% *}
   proton_desktop_mode=${proton_desktop_identity#* }
   case "$proton_desktop_owner:$proton_desktop_mode" in
     *[!0-9:]*|:*|*:|*:*:*)
       printf '%s\n' 'managed Baloo parent identity is malformed' >&2
       exit 1
       ;;
   esac
   if [ "$proton_desktop_owner" != "$(id -u)" ] || [ "$proton_desktop_mode" != 700 ]; then
     printf '%s\n' 'managed Baloo parent must be user-owned with mode 0700' >&2
     exit 1
   fi

   balooctl6 config add excludeFolders "$proton_desktop_root"
   balooctl6 config list excludeFolders
   ```

   Confirm the intended absolute path is listed. This prevents intentional
   recursive indexing; browsing and previews can still fetch files.
3. Reload the user units with `systemctl --user daemon-reload`, run the
   effective-unit qualification block above, then run `proton-drive-desktop
   start` and `proton-drive-desktop status`. Confirm readiness before opening
   Dolphin through `proton-drive-desktop open`.
   During this qualification, confirm that stock rclone and the distribution
   FUSE helper can mount the exact absolute managed pathname as the ordinary
   user and that `findmnt` reports one read-only `fuse.rclone` mount there with
   the launch-specific source tag. Keep the managed parent and mountpoint
   reserved for this service from startup through completed shutdown. No other
   process may rename or replace either directory, mount over the managed
   path, or independently unmount it during the session or logout.
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
credentials. Retained mountpoint ownership or recovery records prevent it
from reporting a completed stop, even when the service is inactive and the
mount has detached. With no records, only an absent target or a user-owned,
empty, unmarked reserved directory is a clean stopped state. An identity
xattr, contents, symlink, non-directory, unsafe directory, or mount is
inconsistent and preserved. If the graphical launcher does not open Dolphin,
run `open` in a terminal to see its fixed diagnostic and inspect `status`.

If `stop` overlaps `_verify-mount` after rclone has mounted, both operations
serialize ownership recording through the private metadata lock. `stop` may
record the still-unverified mount only when its launch tag and every mount
constraint match, then follows the normal unmount-before-process-stop path.
A busy unmount leaves the service running and preserves the recorded mount so
open files can be closed before retrying.

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

Public `stop` also recovers a stable active service with an absent target mount,
including a detach followed by a failed manager stop. It requires two stable
observations, a valid verified ownership record, the unchanged empty underlying
directory, and a final absent-mount check before asking systemd to stop the
service. A mount, replacement, unsafe mode, or unexpected entry that appears at
those boundaries is reported and preserved. `start` and `open` still reject
that state, and no branch uses a forced or lazy unmount or a background restart.

The mountpoint must be on a Linux filesystem that provides persistent,
reliable `user.*` extended attributes for directories. Preparation, launch,
and cleanup fail closed when those xattrs cannot be read, written, or removed;
device and inode numbers alone are never accepted as the directory identity.
Before inspecting contents or xattrs, the helper opens the target with
`O_PATH`, compares its kernel mount ID with the held parent directory, and then
uses a descriptor for directory identity, inspection, and xattr operations.
The initial mount-table absence observation does not authorize later pathname
traversal. The nonce protects against ordinary inode reuse. This procedure
does not claim hostile same-UID forgery or power-loss durability; a process that
can change both the private runtime record and directory xattr, or a filesystem
clone or rollback that reproduces both, remains outside its guarantees.

### Recover an interrupted mountpoint identity operation

Preparation records its intent before creating or identifying the mountpoint,
and retained-directory cleanup records its intent before removing the identity
xattr. A matching retained phase lets preparation finish publishing the
identity automatically. These fixed diagnostics mean the remaining state
cannot be reconciled from the evidence source still has:

- `interrupted mountpoint creation requires stopped recovery`
- `interrupted mountpoint identity publication requires stopped recovery`
- `interrupted retained mountpoint cleanup requires stopped recovery`

Do not copy or guess the recorded nonce. Do not start rclone, edit either JSON
record, remove an unfamiliar xattr, or use forced, lazy, or recursive cleanup.
First ask systemd to stop the unit, then inspect the retained evidence:

```sh
systemctl --user stop proton-drive-desktop.service || :
proton-drive-desktop inspect-recovery
```

`inspect-recovery` reads the effective XDG binding, manager state, mount table,
phase record (`mountpoint-phase.json`), marker, directory metadata, contents,
and application identity xattr. It does not create directories or locks,
change records or xattrs, mount or unmount anything, start or stop a service,
request credentials, or retrieve cloud contents. It refuses when manager state
is unavailable, the unit is not inactive or failed with `MainPID=0`, or any
mount remains at the target.

For an eligible operation it prints the retained phase and one next command:

```text
recovery eligible: prepare-publish
next action: proton-drive-desktop start
```

The evaluator uses the same schemas and phase-specific predicates as recovery
inside the helper. It accepts a user-owned, non-symlink, empty directory when
group and other write bits are clear, including modes `0755` and `0750`. For
`prepare-create`, the marker may be absent or must be a structurally valid
predecessor at the same mount path whose complete contents are committed by the
phase nonce and mount tag. For
`prepare-publish` and `cleanup-retained`, it compares the current device and
inode with the phase before recovery. For `prepare-publish`, the marker may be
absent, the exact planned marker, or the structurally valid predecessor
at the same mount path committed by the phase's mount tag. For
`cleanup-retained`, an absent marker or a prepared or verified marker must
match the phase's mount, device, inode, created flag, nonce, and mount tag; a
verified marker may retain its `mount_id`, and predecessor commitment does not
apply. A present JSON `null`, scalar, array, malformed object, or object with
unsupported fields is invalid rather than absent. The directory identity xattr
may be absent or match the phase nonce.

Apply only the matching branch:

- A `prepare-create` intention does not identify an existing leaf. If the leaf
  is absent, retry `proton-drive-desktop start`; preparation clears the intent
  and creates a newly identified leaf. If a leaf exists, preserve the leaf,
  phase, marker, contents, and xattrs for investigation. Do not infer ownership
  from `created=true` or remove the leaf.
- For `prepare-publish`, require a successful inspection, then retry
  `proton-drive-desktop start`. Preparation accepts the unchanged recorded
  directory, restores the planned application identity when the interrupted
  write left it absent, publishes the marker, and removes the phase. When a
  missing recorded leaf was recreated, the retained predecessor marker is
  accepted only when it names the same mount path and the phase's mount tag
  commits to its complete contents. A different identity, device, inode,
  unrelated or malformed marker, mode, or directory entry preserves every
  record and filesystem object.
- For `cleanup-retained`, require a successful inspection, then retry
  `proton-drive-desktop stop`. Cleanup accepts the unchanged recorded directory
  with the application identity either present or already removed. It removes
  only that identity and the matching private records. It retains the empty
  directory and every other xattr. A failed `start`, `open`, or automatic
  activation refuses this phase during preparation. The following unit
  post-stop hook leaves the retained evidence unchanged; only explicit public
  `stop` revalidates and completes this recovery. This covers marker-present
  and phase-only interruptions.

The result describes only the evidence observed during that invocation. It is
not a durable authorization. Run only the printed `start` or `stop` action;
that action independently rereads and validates the phase, marker, mountpoint,
directory contents, and identity xattr before changing them. If inspection or
the action refuses, preserve the phase, marker, directory, contents, modes, and
xattrs for investigation.

If the private runtime directory is gone, its phase and ownership records are
gone too. An identity xattr without those records remains unknown and is
preserved. A user-owned, empty, non-symlink directory without that xattr is
admitted as preexisting; source cannot infer that the unmarked directory was
helper-created, so later cleanup preserves it.

A runtime marker from an older release has no nonce and cannot authenticate an
existing mountpoint. If the leaf is absent, the next `start` gives the new leaf
a fresh identity automatically. If the leaf remains, first confirm the service
is stopped and the path is unmounted, then inspect the expected user-owned,
empty, non-symlink directory. Only in that stopped-session state, remove the
legacy private runtime marker and retry `start`; the service will adopt the
inspected directory with a new nonce. Do not use matching device and inode
numbers as evidence that the leaf is unchanged.

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
- Launcher: `home/private_dot_local/private_share/applications/proton-drive.desktop.tmpl`
- Behavior and disposable-deployment tests:
  `python3 -m unittest tests.test_proton_drive_desktop tests.test_proton_drive_desktop_deployment`
- Platform bindings: `zsh tests/platform-portability.zsh`

These tests use synthetic files and mocked account/process boundaries.
Before publishing changes, also run the repository's privacy and diff checks
from `AGENTS.md`. Credential or service behavior changes require review of
the changed scope and new host qualification.

### Qualify cleanup retention with a real user manager

The root coordinator must run this fixture on a capable Linux host against the
final reviewed revision. Run it from the repository root as the ordinary user
whose real user manager is under qualification:

```sh
evidence_dir=$(mktemp -d -- "${TMPDIR:-/tmp}/proton-drive-manager-evidence.XXXXXXXX")
python3 tests/test_proton_drive_desktop.py \
  --real-user-manager-cleanup-retention "$evidence_dir"
```

The command prints the absolute receipt path and returns nonzero when the user
manager, its bus, `libsystemd.so.0` sd-bus runtime, rclone 1.75.1, or directory
xattrs are unavailable. It never skips an unavailable requirement.

The fixture keeps its home, config, data, runtime, lifecycle runner, and hook
records under one private directory in the current `XDG_RUNTIME_DIR`. It
validates the ordinary user's existing `XDG_RUNTIME_DIR/systemd/private` as an
owned Unix socket, then places a symlink to that exact socket at the supported
`systemd/private` location inside the fixture runtime. The copied helper still
uses its unchanged systemctl connection behavior. The fixture removes only its
local alias before disposing or retaining the private root; it never removes or
replaces the validated manager socket. It creates one uniquely named transient
service; `systemd-run` uses
`StartTransientUnit` and never calls `daemon-reload`, `link`, or
`show-environment`. Every unit-targeted manager operation names that transient
service. The fixture copies the reviewed production helper byte for byte, then
changes only its service-unit binding to the unique test unit. It records both
hashes and the replacement count in the receipt. After the launcher returns or
raises, the fixture checks that unique unit's load state. A pre-execution launch
exception followed by `not-found` retains its diagnostic and needs no unit stop.
An observed creation receives checked unit cleanup even after a timeout or
nonzero launcher result. A timeout or completed nonzero result followed by
`not-found` leaves the launch outcome unresolved: a pending creation request
may take effect after that separate query. The fixture names the unit
and retains its private files for later checked cleanup; another negative query
or an arbitrary delay does not resolve the outstanding creation request. If the
probe fails or cannot establish the unit state, it likewise reports the launch
failure and retained path. These failures publish no receipt. Keep the files
until the pending launch is resolved and checked unit cleanup establishes that
the unit is absent.

The transient unit receives the known non-secret
`PROTON_DRIVE_FIXTURE_SENTINEL`. Each lifecycle runner records only whether
that name was present before the scrub. It launches the generated lifecycle
file through its `#!/bin/sh` shebang and an `env -i` boundary containing only
`HOME`, `LANG`, `PATH`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and
`XDG_RUNTIME_DIR`. The shell-side record requires all six names and permits
only the supported shell's `PWD`, `SHLVL`, and `_` housekeeping names. Before
the lifecycle file invokes the copied helper, a second `env -i` passes exactly
the six declared names. The records contain names and Boolean sentinel state,
never values. The sentinel and arbitrary inherited names must be absent from
both scrubbed boundaries. Because the unchanged helper passes its own
environment to the fixed `/usr/bin/rclone version` command, this also checks
that the version process receives the helper's minimal environment. A
synthetic mode-0600 config and valid `cleanup-retained` evidence exercise no
credential client, FUSE, provider, installed Proton service, or network.

Accept the receipt only when all of this evidence is present:

- The local rclone preflight and the hook's own version check both see exactly
  rclone 1.75.1. An unavailable executable or another version is a prerequisite
  failure, not lifecycle evidence.
- The manager start returns nonzero. The start-pre record contains status 1,
  empty standard output, and exactly `interrupted retained mountpoint cleanup
  requires stopped recovery` on standard error. The post-stop record contains
  status 0 with no diagnostic. The manager properties independently show
  `ExecStartPre` status 1 and `ExecStopPost` status 0 for the lifecycle runner.
- The manager reports the exact unique unit, `Transient=yes`, failed state, and
  no main or control process. The `before` and `after_failed_start` recovery
  snapshots are identical.
- Public `stop` against the copied helper's unique unit removes the phase,
  marker, and product identity xattr while preserving the directory identity,
  mode, empty contents, and every unrelated xattr recorded before startup.
  The before snapshot must contain the expected product identity; only that
  attribute is removed from the expected after snapshot.
- Public stop and checked teardown require that exact unit to be stopped
  (`inactive` or `failed`) with `MainPID=0` and `ControlPID=0`. Checked teardown
  then resets its failed state, verifies `inactive` with both process IDs still
  zero, releases the narrow
  unit reference that kept the transient unit inspectable during public
  recovery, and requires final `LoadState=not-found`. One persistent sd-bus
  connection owns `RefUnit` through public recovery and final inspection, then
  performs `UnrefUnit` on that same connection. Failure cleanup closes the
  connection after attempting checked unit cleanup.
- The fixture builds receipt data only after qualification and checked unit
  cleanup succeed. It disposes the private temporary root, writes a mode-0600
  sibling temporary receipt in the evidence directory, and atomically renames
  that file to the final JSON path. The temporary root is absent when the final
  receipt becomes visible.

Any prerequisite, manager-socket validation or alias cleanup, hook, diagnostic,
manager-property, public-stop, evidence, teardown-stop, reset, reference
release, collection, temporary-root disposal, or receipt-publication failure
returns nonzero and leaves no qualifying final receipt. Missing bus or socket
capability is a failure, never a skip. An unexpected fixture-local alias state
retains the private root and does not authorize changes to the target socket. A
teardown error names the exact transient unit and the retained private-file
path, and reports the failed operation or exception. Completed manager-command
failures use operation-specific messages; the fixture does not report their
captured output or translate negative reference-release results. If that
happens, keep the command output and those files, and use only that reported
name for checked cleanup:

```sh
unit=proton-drive-cleanup-retention-REPLACE_WITH_REPORTED_SUFFIX.service
systemctl --user stop "$unit"
systemctl --user show "$unit" \
  --property=ActiveState --property=MainPID --property=ControlPID
systemctl --user reset-failed "$unit"
systemctl --user show "$unit" --property=LoadState --value
```

Require inactive state, zero main and control PIDs, successful reset, and
`not-found` from the final command. Do not reload the manager, remove a unit
file, or treat failed cleanup as qualification. If these checks cannot be
established, preserve the output and report the host gap.

This fixture qualifies the failed `ExecStartPre` to `ExecStopPost` sequence,
the later explicit-stop recovery, and collection of its transient test unit.
The scratch synthetic boundary proves the fixture's connection-ownership,
disconnect, launch-rejection and timeout handling, inconclusive probes,
environment, disposal, and receipt rules; it does not prove a real
manager's sender-scoped reference lifetime or garbage-collection timing. Only
this root-coordinated host invocation can supply that evidence. The fixture
does not qualify the installed unit, Plasma login or logout, KWallet, Secret
Service, FUSE, rclone mounting, credentials, or provider behavior. Keep
those activation gates in the host qualification above. Synthetic manager
faults in the ordinary suite are labeled constructed negatives and cannot
substitute for this coordinator-run real-manager proof. The fixture assumes no
hostile same-user mutation during its bounded run; unexpected alias state is an
unresolved failure, not qualification.

Baloo's [settings schema](https://github.com/KDE/baloo/blob/master/src/lib/baloosettings.kcfg)
defines folder exclusions. The installed `balooctl6 config` help describes
the operator commands above.
