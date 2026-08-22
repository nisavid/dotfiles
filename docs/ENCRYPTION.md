# Encryption

This repository stores private configuration as recipient-encrypted [age](https://age-encryption.org) ciphertext. The configured key uses age's hybrid ML-KEM-768 and X25519 recipient scheme (`age-keygen -pq`). Private plaintext belongs only at its intended target or in a mode-restricted transaction phase.

## Configuration

[`home/.chezmoi.toml.tmpl`](../home/.chezmoi.toml.tmpl) configures age with the committed public recipient and the machine-local identity at `~/.config/age/key.txt`. The identity must remain mode `0600`; [`home/.chezmoiignore`](../home/.chezmoiignore) prevents chezmoi from managing it.

Dot-prefixed ciphertext files are source-only data. Chezmoi ignores them as targets, while templates and the private-skill restore hook can read them.

## Encrypted Sources And Plaintext Targets

- `home/.private-agents.md.age` supplies the private section of `home/dot_codex/private_AGENTS.md.tmpl`. Chezmoi renders the combined policy only to `~/.codex/AGENTS.md`; the `private_` source attribute gives that target mode `0600`.
- `home/.private-codex-work.toml.age` supplies private Codex writable roots and trusted project paths to the mode-`0600` `~/.codex/config.toml` overlay.
- `home/.private-git-identities.toml.age` supplies hostname selection, identity records, editor preference, branch prefix, and tracking policy to generated configuration targets. Public data contains only a synthetic fixture and the allowed personal fallback.
- `home/.private-machine.toml.age` supplies machine-local checkout paths and identity-bearing GnuPG configuration.
- `home/.private-hindsight.toml.age` supplies the complete Darwin-only Hindsight consumer binding. Public Hindsight data contains only the reusable release pin.
- `home/.private-secret-exec.toml.age` supplies secret-provider locators and command-to-profile bindings. It never contains credential values.
- `home/.private-privacy-denylist.txt.age` supplies exact private identifiers to the local privacy scan. Hosted CI runs the generic scan without decrypting this file.
- `home/.private-prd-01.toml.age` is a source-only private requirements catalog with no plaintext target.
- Each neutral `home/.private-skill-NN-path.age` and `home/.private-skill-NN-body.age` pair contains one relative skill path and its `SKILL.md`. The pair numbers reveal neither skill name nor destination. The restore transaction validates each pair, installs a mode-`0700` directory at `~/.agents/skills/<path>` with a mode-`0600` `SKILL.md`, and creates the corresponding relative symlink under `~/.claude/skills`.

Do not add a plaintext private partial, deployment catalog, identity registry,
skill path, or skill body to the source tree.

Before publication, run both scan layers:

```zsh
AGE_TOOLING_DIRECTORY=/absolute/path/to/checksum-verified-age-bin \
  python3 scripts/privacy-scan --root . --require-age-manifest
chezmoi decrypt home/.private-privacy-denylist.txt.age |
  AGE_TOOLING_DIRECTORY=/absolute/path/to/checksum-verified-age-bin \
    python3 scripts/privacy-scan --root . --require-age-manifest --denylist -
```

The scanner reports only a path, line, and rule. It never echoes the matched
value.

### Ciphertext admission

The root `.privacy-age-envelopes.json` is the closed, canonical inventory of
every regular `*.age` source path and its exact SHA-256 digest. Hosted and local
scans require the inventory and age v1.3.1's structural parser. Both reject an
unlisted, missing, renamed, malformed, oversized, or byte-changed ciphertext
and still scan the exact ciphertext bytes for plaintext credential and
private-key canaries. `age-inspect` does not authenticate a payload and cannot
by itself distinguish a complete native envelope from a truncated or extended
byte stream.

The manifest is an integrity inventory, not an authenticated admission
receipt. The `pull_request_target` boundary executes only verifier and scanner
code from the exact trusted base commit and treats the pull-request checkout as
data. It rejects any candidate change to ciphertexts, this inventory, the
recipient configuration, admission or scanning code, encryption policy, or any
workflow unless a trusted owner admission is present. Ordinary pull requests
cannot mint admission authority by editing the candidate manifest, labels, or
comments.

### Owner admission receipts

After the candidate commit is final, use an operator-owned wrapper copied to a
location outside both the trusted and candidate checkouts. The wrapper reads the
receipt creator as a raw blob from the trusted base commit, compares it with the
live trusted-checkout file before execution, and executes only the verified blob.
Do not run a wrapper from either checkout. The creator then requires both
checkouts to be clean (including untracked and ignored files), materializes the
exact candidate Git tree, and independently validates every envelope with the
machine-local identity in check-only mode before signing a canonical,
secret-free receipt with the owner admission key. Its in-process source check is
defense-in-depth; the external wrapper is the independent launcher trust root:

For an ordinary transition, materialize the wrapper from the already trusted
base commit into an operator-owned mode-`0755` location and verify that copy
before use. During the one-time bootstrap, use a separately reviewed external
copy of the bootstrap wrapper; the pre-bootstrap base cannot supply it yet.
In either case, verify the external file is a regular mode-`0755` file and
compare its SHA-256 with the reviewed wrapper source before invoking it.

For a materialized wrapper, establish the operator-owned copy and its reviewed
digest before the invocation above:

```zsh
wrapper_parent=$(dirname -- "$TRUSTED_ADMISSION_WRAPPER")
test -d "$wrapper_parent"
test ! -L "$wrapper_parent"
temporary_wrapper=$(mktemp "$wrapper_parent/.admission-wrapper.XXXXXX")
trap 'rm -f -- "$temporary_wrapper"' EXIT HUP INT TERM
git -C "$TRUSTED_MAIN_CHECKOUT" show \
  "$BASE_COMMIT:scripts/run-trusted-age-admission" \
  >"$temporary_wrapper"
chmod 0755 "$temporary_wrapper"
test -f "$temporary_wrapper"
test ! -L "$temporary_wrapper"
mv -f -- "$temporary_wrapper" "$TRUSTED_ADMISSION_WRAPPER"
trap - EXIT HUP INT TERM
test -f "$TRUSTED_ADMISSION_WRAPPER"
test ! -L "$TRUSTED_ADMISSION_WRAPPER"
stat -f '%Sp %N' "$TRUSTED_ADMISSION_WRAPPER" 2>/dev/null ||
  stat -c '%A %n' "$TRUSTED_ADMISSION_WRAPPER"
printf '%s  %s\n' "$REVIEWED_WRAPPER_SHA256" "$TRUSTED_ADMISSION_WRAPPER" |
  shasum -a 256 --check
```

```zsh
# Supply these operator-owned locations outside this document.
: "${TRUSTED_MAIN_CHECKOUT:?set TRUSTED_MAIN_CHECKOUT to the trusted checkout}"
: "${CANDIDATE_CHECKOUT:?set CANDIDATE_CHECKOUT to the candidate checkout}"
: "${TRUSTED_ADMISSION_WRAPPER:?set TRUSTED_ADMISSION_WRAPPER to external wrapper}"
: "${AGE_IDENTITY:?set AGE_IDENTITY to the external age identity}"
: "${ADMISSION_SIGNING_KEY:?set ADMISSION_SIGNING_KEY to the external signing key}"
: "${AGE_TOOLING_DIRECTORY:?set AGE_TOOLING_DIRECTORY to verified age tooling}"
: "${ADMISSION_RECEIPT_OUTPUT:?set ADMISSION_RECEIPT_OUTPUT to an external output file}"
BASE_COMMIT=0123456789abcdef0123456789abcdef01234567
HEAD_COMMIT=89abcdef0123456789abcdef0123456789abcdef
AGE_TOOLING_DIRECTORY="$AGE_TOOLING_DIRECTORY" \
  python3 "$TRUSTED_ADMISSION_WRAPPER" \
  --base-repository "$TRUSTED_MAIN_CHECKOUT" \
  --base-commit "$BASE_COMMIT" \
  -- \
  --base-repository "$TRUSTED_MAIN_CHECKOUT" \
  --base-commit "$BASE_COMMIT" \
  --head-repository "$CANDIDATE_CHECKOUT" \
  --head-commit "$HEAD_COMMIT" \
  --repository nisavid/dotfiles \
  --identity "$AGE_IDENTITY" \
  --signing-key "$ADMISSION_SIGNING_KEY" \
  --trusted-admitter "$TRUSTED_MAIN_CHECKOUT/scripts/admit-age-envelopes" \
  --output "$ADMISSION_RECEIPT_OUTPUT"
```

The output is one bounded `privacy-age-admission/v1` pull-request-body marker.
Add exactly that marker to the pull request body after the candidate head is
published. Editing the body triggers the trusted boundary workflow. The
workflow computes the protected transition itself, then requires the receipt
to match the repository, base and head commits, every protected path's mode,
kind, and SHA-256 digest, the expiry window at the time the workflow runs, and
the signature namespace and principal. A changed head requires a new receipt;
an expired or ambiguous marker fails closed during that run. GitHub preserves a
successful required-check conclusion after the receipt expires, so the owner
must trigger a fresh trusted run after adding the marker and immediately before
merging. The check is not a time-based merge gate by itself.
The nonce identifies the signed receipt but is not a one-time ledger. A valid
receipt may be replayed only for the exact base/head transition until its
expiry; changing either commit requires a new receipt.

The committed public verifier key is
`.github/age-admission/allowed_signers`. Rotate that key only as another
owner-admitted protected transition. Never send the age identity, signing
private key, decrypted catalog, or decrypted diagnostics to hosted CI. The
receipt contains no plaintext identifiers.

The first bootstrap of this boundary is a one-time exception: the trusted
base predates the signer and verifier paths, so it cannot verify a v1 receipt.
Freeze other `main` merges while the exception is open and, immediately before
the break-glass action, verify from the live base commit that none of the four
new admission pathnames already exists. A pre-seeded placeholder would be
trusted by the legacy pre-bootstrap gate, so the owner must compare the exact
bootstrap tree and branch-protection preimage before authorizing this one
transition.
Create the bootstrap branch from `main` and open its pull request targeting
`main`. The branch must contain and replace every admission infrastructure path
before the exception is used: the signer, external launcher wrapper, creator,
admission module, legacy admitter, envelope helper, trusted gate, and boundary
workflow. Keep its review and required checks visible, and use an owner-approved,
branch-scoped break-glass exception only long enough to merge that pull
request. Do not push directly to `main`, disable unrelated protections, or
reuse the exception for ordinary changes. Re-enable the protection
immediately, verify that `main` contains the signer and verifier paths, and
record the exact Checks API `name` emitted by the job — currently
`Verify trusted base against candidate data` (the UI may render it with the
workflow name prefixed). Read that name from a fresh check run. Do not treat
that Actions job name as the final authenticated admission requirement; verify
the dedicated App-pinned context described below through the live
branch-protection API before creating a receipt for the next protected pull
request.

The Actions job name is not a provenance boundary: GitHub keys a required
check by its job name and the shared Actions app, without binding it to the
trusted `pull_request_target` workflow. Before ordinary protected merges,
install a repository-scoped GitHub App dedicated to this admission controller,
have it publish a stable admission context, and pin that context to the App ID
in branch protection. Verify the live API preserves every existing check,
strictness, administrator enforcement, review requirement, and the new
App-pinned context. Until that App-backed source is installed and verified,
keep ordinary protected merges owner-controlled and treat the Actions check as
advisory; do not claim that the bootstrap workflow alone closes the merge
boundary.

The v1 repository policy authorizes exactly one post-quantum recipient stanza
per ciphertext. Hosted scanning enforces that public structural invariant;
admission binds the single stanza to the supplied identity by independently
decrypting the exact bytes. To rotate or add a machine, re-encrypt and admit the
repository as a separately reviewed policy change rather than adding an
unaccounted recipient.

After adding, replacing, removing, or re-encrypting any age source, regenerate
the inventory with the machine-local identity outside the repository:

```zsh
AGE_TOOLING_DIRECTORY=/absolute/path/to/checksum-verified-age-bin \
  python3 scripts/admit-age-envelopes \
  --root . \
  --identity ~/.config/age/key.txt
AGE_TOOLING_DIRECTORY=/absolute/path/to/checksum-verified-age-bin \
  python3 scripts/privacy-scan --root . --require-age-manifest
```

The admission command requires age v1.3.1 from an absolute, trusted installation
directory outside the repository, exactly one mode-`0600` post-quantum identity
outside the repository, and exactly one ML-KEM-768+X25519 recipient stanza. The
trusted directory should come from a checksum-verified package installation,
not an ambient `PATH` lookup. Every resolved executable in both the trusted
directory and the ambient `PATH` must remain outside the repository. Admission
requires the ambient tool bytes to match the trusted installation, then executes
private staged copies before opening the identity. That identity must
independently decrypt every exact candidate to EOF. The command reads each
candidate once with a 4 MiB limit before atomically and durably replacing the
manifest. It discards plaintext and age diagnostics. The command leaves the
existing manifest unchanged if any path is unsafe, any envelope fails
decryption, or any other validation fails. Review the ciphertext and manifest
together; do not hand-edit a digest to admit bytes that were not validated by
this command. Exit status `2` with `age-envelope manifest durability uncertain`
means the exact new manifest bytes are installed but the directory durability
commit could not be confirmed; inspect the installed manifest and rerun
admission before treating it as durable.

`--check-only` runs the same identity-backed validation without replacing the
manifest. It also requires the committed manifest to equal the manifest that
validation computed, so a stale or hand-edited inventory fails the check. The
receipt command uses this mode against the final candidate tree before it signs
the transition.

## Source-Only Catalog Editing

Edit a source-only catalog in a mode-`0700` temporary directory with a
mode-`0600` plaintext file. Decrypt without writing plaintext to standard
output, keep editor swap and backup files inside that phase, validate the
catalog, re-encrypt to a temporary ciphertext with the committed recipient,
and atomically replace the source ciphertext. Remove the plaintext phase on
success, failure, or interruption. Never render the catalog into the repository
or a persistent plaintext target.

## Transactional Private-Skill Restore

`home/run_onchange_after_restore-private-skills.sh.tmpl` hashes every ciphertext pair for change detection and passes the pairs to `scripts/private-skill-transaction`. The transaction:

1. Acquires a cooperative lock under `${XDG_STATE_HOME:-~/.local/state}/chezmoi/private-skill-transaction`.
2. Decrypts and validates every pair in a mode-`0700` phase with mode-`0600` files before changing a target.
3. Saves encrypted recovery metadata and snapshots before publishing the replacement set.
4. Installs and verifies every supplied skill and symlink pair. It then records completion and removes recovery state.

The supplied pairs are transactional inputs, not an authoritative inventory. Removed pairs are not pruned automatically. Remove obsolete live skill targets explicitly under separate authorization.

On a catchable failure, the transaction restores the previous set before returning an error. After an interruption, the next transaction acquisition inspects the encrypted recovery pointer: a pending transaction rolls back to the verified old set, while a completed transaction verifies the published set before clearing recovery data. It refuses recovery when live targets conflict with both the recorded old and desired states.

## Key Backup And Recovery

Back up `~/.config/age/key.txt` in a password manager or offline encrypted store. There is no password fallback. Losing every copy makes the ciphertext unrecoverable.

On a new machine:

1. Install age and chezmoi.
2. Restore `~/.config/age/key.txt` and set mode `0600`.
3. Run `chezmoi init --apply nisavid/dotfiles`.

Initialization writes chezmoi's age configuration before apply. With the correct identity, apply renders the private target files and invokes the transactional skill restore. Without it, decryption fails and the private targets cannot be rendered; restore the identity and rerun apply.

## Rotation And Additional Machines

The v1 single-stanza policy supports a reviewed cutover, not a multi-recipient
overlap. Generate a new post-quantum identity, re-encrypt every ciphertext only
to the new recipient, admit the complete repository with that identity, and
verify the new machine before retiring the old identity. Machines retaining
only the old identity cannot decrypt the rotated repository.

An overlap window requires a separately reviewed policy change that raises the
authorized stanza count and updates admission and hosted scanning together.
Never add an extra recipient under the v1 policy, and do not mix post-quantum
and classical recipients because the classical recipient determines the weaker
confidentiality boundary.
