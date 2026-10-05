# Recover Provingkit alpha.4 artifact inputs

Use this procedure when preparing alpha.4's recovery packet, accepting its
off-machine custody, or reconstructing its artifact directories in a fresh
home. Recover the reviewed inputs before following the
[installation procedure](provingkit-installations.md). Alpha.4 retains its
manual local-marketplace route for Codex and Claude; Cursor is outside this
recovery selection.

This candidate-specific route requires operator retrieval from Proton Drive.
It establishes manual artifact recovery, not unattended chezmoi recreation,
plugin activation, or runtime acceptance. Recovery preparation and acceptance
do not hold the separately approved local installation. Signing and release or
marketplace publication are independent work.

## Bind the packet and procedure

Use a reviewed, retrievable dotfiles revision containing this procedure, the
[authored declaration](../../home/.chezmoidata/provingkit.json), and the
[importer](../../home/private_dot_local/bin/executable_provingkit-installations).
Record that revision before using it. The declaration's `recovery_packets`
entry binds the named packet and independent pins; the
[selection projection](../../home/.chezmoitemplates/provingkit-selection.tmpl)
makes it available without activating an installation profile.

Each `provingkit-recovery-selection-v1` entry records the version, source
repository and commit, supported platform, packet byte count and SHA-256,
manifest SHA-256, intended remote path, and retention rule. The alpha.4 entry
is named `alpha4-8f57be695ae0-linux-amd64`. Its `intended_remote_path` is a planned
destination, not evidence of an existing object. Read the entry and
`provingkit-installations import-artifacts --help` for exact command inputs.
Use the independently recorded packet and manifest digests as trust anchors;
an unverified downloaded manifest cannot establish those anchors.

Keep the reviewed clean archives, the canonical targets' ordinary receipts,
the separate Codex alias receipt, mode manifests, and reconstruction
instructions together. The packet inventory describes regular files only.
Include the complete catalogs required by its selected targets; client and
member selection retain their separate installation approval. Exclude
credentials, signing keys, native installation backups,
private account evidence, and unrelated configuration.

Each packet has an immutable directory under this Proton Drive hierarchy:

```text
/my-files/Project Recovery/Provingkit/0.1.0-alpha.4/
  source-<full source commit>/packet-sha256-<full packet digest>/
```

Take the full source commit, packet digest, and exact remote path from the
reviewed declaration, and constituent pins from its digest-bound manifest.
Create a new directory for changed packet bytes; preserve existing packets
rather than overwriting or merging them.
Record an actual remote path only after verifying the created location. A
declared destination does not establish custody.

## Establish interactive access

Use the official `proton-drive` CLI through an unlocked Linux desktop Secret
Service session. The [retained synthetic pilot](https://github.com/nisavid/dotfiles/issues/290#issuecomment-5994569813)
supports this manual transfer interface. It does not establish current account
authentication, replacement-machine authentication, or retrieval of this
packet. Check the installed version and required command help before use;
changed interfaces require a fresh review.

Before authentication or transfer:

1. Select `PROTON_DRIVE_CREDENTIALS_STORE=keychain` and
   `PROTON_DRIVE_UNSAFE_CACHE=false`. Require the desktop secret store to be
   available and unlocked. Check session metadata without reading or displaying
   the stored secret.
2. Require `PROTON_DRIVE_CACHE_DIR` to be absent from the launched process. A
   nonempty override redirects application data, cache, and logs together.
   Resolve the effective application-data directory using `XDG_DATA_HOME` and
   require `auth-session.json` to be absent. Stop on a plaintext-session file or
   an unverified storage binding; preserve the finding for its owner.
3. Reuse a valid session. If sign-in is needed, use the official browser flow
   only within its approved scope. Protect CLI output in a mode-0600 temporary
   file: the sign-in URL contains authentication material and must stay out of
   transcripts, shared logs, and committed evidence. Verify successful keychain
   persistence and the continued absence of a plaintext session file. Record
   only the redacted result, then delete the protected temporary output.

Storage or persistence failures stop the operation. This procedure uses the
existing interactive authentication route; it neither copies Hatchery's
credentials to another machine nor establishes access before desktop login.

## Retain and retrieve the packet

Review the exact packet and its independently pinned declaration before
requesting upload approval. The approval names those bytes and the destination;
plan confirmation alone does not authorize Drive writes. Use the existing
remote parent and retain the resulting path and transfer report.

The CLI exposes these transfer shapes:

```sh
proton-drive filesystem upload --json "$local_packet" "$remote_parent"
proton-drive filesystem download --json "$remote_packet" "$empty_download_directory"
```

After upload, independently download the actual packet into a new empty local
directory. Compare every relative path, file size, and SHA-256 with the
independently retained packet inventory, including the declared packet digest.
Require the complete inventory with no missing, extra, renamed, or mismatched
files. The CLI can report success while skipping files, so its exit status is
not custody acceptance. Use ordinary files; the download command's handling of
Proton Docs and Sheets is outside this packet format.

For later recovery, obtain the reviewed declaration independently, establish
interactive access on the recovery machine, and repeat the empty-directory
download and complete comparison. Stop before import if verification differs.

## Import without activating installations

Run the public importer with the reviewed recovery name and verified local
packet:

```sh
provingkit-installations import-artifacts --recovery "$recovery_name" \
  --packet "$verified_packet"
```

The importer verifies the packet, every selected target's archive, catalog,
file inventory, tree digest, and modes, and the canonical targets' ordinary
receipts before publishing the reconstructed content-addressed artifact and
evidence directories. It verifies the Codex alias against the canonical
artifact and its separate parent-bound receipt.
Artifacts are retained under
`~/.local/share/provingkit/artifacts/<target>/<tree-sha256>/`, with separate
receipt and mode evidence under the matching
`evidence/<target>/<tree-sha256>/` directory. The Codex alias uses the distinct
`agent-plugins-local` target. Matching existing directories produce a no-op. A
mismatched existing directory is preserved and causes refusal; inspect it with
its owner before retrying. Publication proceeds one directory at a time. An
interruption or I/O failure can leave earlier verified directories or partial
new directories; a later import preserves these and refuses any partial
content. Inspect that state before arranging cleanup or retrying.

The command emits JSON. A first import reports `artifacts_imported`; a verified
repeat reports `artifacts_verified`, both with exit status 0. Invalid selection
metadata or missing flags reports `invalid_selection` with status 64; an
unsupported platform reports `unsupported_platform` with status 2. Packet validation or filesystem
failures report `recovery_invalid`, while an existing destination conflict
reports `recovery_refused`, both with status 1. This recovery route
supports Linux on AMD64.

Import invokes no native clients, writes no installation observation receipt,
and enables no profile. Keep the installation profile inactive during recovery
acceptance. Use the import route directly; the local `file://` fixture allowance
is never part of recovery or host deployment. Native registration, enablement,
cache changes, and live installation follow their own reviewed procedure and
approval afterward.

## Accept recovery and retain custody

Acceptance requires all of these observations on the same reviewed packet and
procedure revision:

- An independent download from the retained remote location matches the
  external packet pin and every expected regular file.
- Import into a disposable fresh home reconstructs the declared artifact and
  evidence directories, including files, modes, ordinary receipts, and the
  recovered Codex alias binding.
- A second import leaves the reconstructed content unchanged; missing or
  mismatched packet inputs are rejected before materialization, and mismatched
  existing directories remain unchanged.
- The exercise invokes no native clients and leaves the profile inactive.

Record the declaration and procedure revision, packet identity and remote
location, download comparison, reconstruction results, and any unverified
authentication or client behavior in the owning recovery record. A local test
with constructed inputs establishes importer behavior only. Actual retrieval
and fresh-home reconstruction establish this packet's manual recovery; neither
substitutes for replacement-machine authentication or native runtime acceptance.

Keep the retained packet until a replacement recovery source has been
independently retrieved and verified, then obtain Ivan's explicit retirement
approval before deletion. There is no automatic expiry. Hindsight's memory
backup retention rules do not govern these artifact packets. General
unattended reconstruction remains unfinished under
[dotfiles #300](https://github.com/nisavid/dotfiles/issues/300).
