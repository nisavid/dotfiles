# Encryption

This repository stores private configuration as recipient-encrypted [age](https://age-encryption.org) ciphertext. The configured key uses age's hybrid ML-KEM-768 and X25519 recipient scheme (`age-keygen -pq`). Private plaintext belongs only at its intended target or in a mode-restricted transaction phase.

## Configuration

[`home/.chezmoi.toml.tmpl`](../home/.chezmoi.toml.tmpl) configures age with the committed public recipient and the machine-local identity at `~/.config/age/key.txt`. The identity must remain mode `0600`; [`home/.chezmoiignore`](../home/.chezmoiignore) prevents chezmoi from managing it.

Dot-prefixed ciphertext files are source-only data. Chezmoi ignores them as targets, while templates and the private-skill restore hook can read them.

## Encrypted Sources And Plaintext Targets

- `home/.private-agents.md.age` supplies the private section of `home/dot_codex/private_AGENTS.md.tmpl`. Chezmoi renders the combined policy only to `~/.codex/AGENTS.md`; the `private_` source attribute gives that target mode `0600`.
- `home/.private-codex-work.toml.age` supplies private Codex writable roots and trusted project paths to the mode-`0600` `~/.codex/config.toml` overlay.
- `home/.private-daybreak-account-bindings.md.age` supplies exact Codex account-home bindings to the mode-`0600` `~/.agents/daybreak-account-bindings.md` target. Public policy may name only this neutral target path; exact account homes, authenticated identities, classifications, and other properties remain private. The local/private catalog may be read and correlated for routing and actionable per-account status, while any nonlocal or public persistence or transmission must scrub account homes, account IDs, stable per-account labels, and derived identifiers; use only a generic non-stable marker or redacted status there. Credentials, tokens, decrypted secrets, and task data remain excluded.
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

The trusted-base scanner discovers
`.github/age-admission/privacy-scan-reviewed-findings-v1.json` relative to its
own checkout (or accepts an explicit `--review-record` path). The discovered
record is considered when the candidate reproduces a reviewed finding key;
clean or unrelated candidates are scanned normally and cannot inherit a
disposition for findings they did not produce. This is a versioned owner-review
record, not a path or rule allowlist. Each entry names the scanner rule and one
closed owner-attested semantic category, then binds the canonical repository
path, regular-file mode, Git blob, and complete file-byte SHA-256. The scanner
rejects unknown categories and a mismatch between `category` and
`evidence.kind`; it does not derive or prove the owner's semantic attestation.
Every review-record path component is restricted to ASCII letters, digits,
periods, underscores, and hyphens; components containing spaces or unsupported
punctuation are not valid review identities even when another admission payload
accepts them.
Scanner reads, reviewed finding files, and bound policy files share an inclusive
4 MiB per-file limit. The compact JSON review record has a separate inclusive
512 KiB limit. A public file above 4 MiB remains an `oversized-public-file`
finding and cannot be owner-dispositioned.
The scanner recomputes the complete finding set and fails closed on any missing,
new, changed, duplicated, or partially stale applicable record. The record is
read from the trusted-base checkout; a candidate-authored copy is never
consulted. An explicit `--review-record` path is diagnostic only: the scanner
validates it against the complete finding set, reports every finding, and never
uses it for suppression. A nonempty explicit record with no current key is
stale and fails. A valid auto-discovered record with no current-key intersection
is irrelevant, so a clean candidate passes and unrelated findings remain
ordinary failures. Any partial intersection makes the auto-discovered record
applicable and requires exact equality with the complete finding set. The
record's `reviewed_commit` names the candidate source under review as provenance; its
policy-file hashes independently bind the trusted scanner policy that consumes
it. Changes to the record or scanner remain inside the owner-admission boundary.

Update this coupled boundary in dependency order: finish the trusted scanner and
policy-file bytes first; recompute the record's `policy.files` digests and entry
identities second; then update the integrity gate's exact Git blob pins for the
changed scanner, record, documentation, and corresponding test fixtures.

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

The workflow contains the legacy-protected `owner-signed-age-v1` activation
sentinel. Keep that marker in every admitted workflow revision; the gate rejects
an active transition that removes it, so recovery cannot silently fall back to
the pre-bootstrap path.

This verifier revision recognizes commit
`0e981202824a76043083039a407dd165e243d544` as the only active predecessor whose
seven-path admission boundary precedes the current nine-path boundary. Ordinary
predecessor admission cannot install that expansion: the predecessor binds only
four changed protected paths, while the current verifier also requires the
canonical reviewed-findings record and reviewer module. A predecessor-scoped
receipt therefore cannot describe the complete transition required by the
current boundary.

The one-time transition requires a separately reviewed, immutable compute
bundle executed outside both Git checkouts. It binds the exact predecessor,
candidate tree, two new authority paths, complete protected delta, reviewed
finding set, and ordinary owner-signed receipt before handing a canonical result
to the separately deployed App bootstrap publisher. This repository revision
does not implement or activate that external transition mechanism. The same
seven-path shape at any other commit, any mixed or malformed boundary, and any
later deletion or downgrade remain blocking before receipt parsing.

### Every-head admission result

The repository-scoped App publishes the required `Owner-signed age admission`
context from App ID `4695065` for every pull-request head. The trusted-base
protected-path calculation is the discriminator, not the presence of a receipt
in the pull-request body:

- an empty protected-path set publishes terminal success with the exact
  `no_protected_paths_changed` result and does not parse or require a receipt;
- a nonempty set requires one exact owner-signed receipt and publishes
  `owner_admission_verified` only after the receipt is bound to the repository,
  base, head, complete transition, signer, and validity window;
- checkout, classifier, repository, commit, freshness, provenance, or binding
  uncertainty remains blocking and must never be reported as an empty set.

The result vocabulary and exact-head/idempotency contract are recorded in
[`docs/privacy-age-admission-result-v1.md`](privacy-age-admission-result-v1.md).
The App publishes this context for opened, reopened, synchronize,
ready-for-review, and edited pull-request events. Duplicate or out-of-order
deliveries cannot replace a newer head's result. The trusted Actions workflow
remains advisory evidence for the App-pinned context; it is not a substitute
for the required App result, and branch protection is not edited dynamically.
A default-branch push does not identify a pull request; the App/event layer
must re-evaluate every open pull request targeting `main` against the new base
before an existing result is treated as current. The workflow does not
enumerate pull requests from a push payload or publish without its trusted
verifier handoff, so bounded enumeration, this reconciliation, and its live
delivery proof remain deployment gates. The installation proof must show the
App receives default-branch push and pull-request events with only the read
permissions needed for that coordinator; it remains separate from the
publisher job's short-lived `checks:write` token.
The coordinator must also prevent an old same-head success from surviving a
body edit, retarget, reopen, base advance, cancellation, duplicate create, or
accepted-write response loss. Per-PR serialization, event-time invalidation,
and compensating failure reconciliation require separate source and live proof;
`external_id` is audit metadata, not a lock.
The Checks API also caps per-ref history; `filter=all` and Link pagination do
not by themselves prove that older duplicates are visible. The installation
lane must prove the history bound or separately review a suite-by-suite
reconciliation path before activation.
For fork heads, a Checks API response can lack a pull-request association;
the installation lane must prove the exact PR-visible App context rather than
inferring delivery from an accepted HTTP response.

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
before use. Verify the external file is a regular mode-`0755` file and compare
its SHA-256 with the reviewed wrapper source before invoking it. Use a freshly
created, private mode-`0700` wrapper directory; the launcher also rejects any
group/world-writable or foreign-owned ancestor at invocation time.

The initial bootstrap is not an owner-side receipt or manual helper operation.
It is supplied by the separately reviewed immutable event-driven publisher
described below. Do not set a bootstrap exception flag, publish a check manually,
edit branch protection, or mint a receipt for an unprotected transition. The
publisher and its protected environment remain operator-owned deployment gates;
until they are approved and live, this workflow is advisory and no production
activation is claimed.

For a materialized wrapper, create and validate the operator-owned directory
without mutating an existing path, then establish the copy and its reviewed
digest before the invocation above:

```zsh
set -euo pipefail
: "${TRUSTED_MAIN_CHECKOUT:?set TRUSTED_MAIN_CHECKOUT to the trusted checkout}"
: "${TRUSTED_ADMISSION_WRAPPER:?set TRUSTED_ADMISSION_WRAPPER to external wrapper}"
: "${REVIEWED_WRAPPER_SHA256:?set REVIEWED_WRAPPER_SHA256 to the reviewed wrapper digest}"
: "${BASE_COMMIT:?set BASE_COMMIT to the reviewed trusted base commit}"
wrapper_parent=$(dirname -- "$TRUSTED_ADMISSION_WRAPPER")
test -d "$wrapper_parent"
test ! -L "$wrapper_parent"
wrapper_parent_mode=$(stat -c '%a' "$wrapper_parent" 2>/dev/null ||
  stat -f '%Lp' "$wrapper_parent")
wrapper_parent_uid=$(stat -c '%u' "$wrapper_parent" 2>/dev/null ||
  stat -f '%u' "$wrapper_parent")
test "$wrapper_parent_mode" = 700
test "$wrapper_parent_uid" = "$(id -u)"
wrapper_mode=$(git -C "$TRUSTED_MAIN_CHECKOUT" ls-tree "$BASE_COMMIT" \
  -- scripts/run-trusted-age-admission | awk 'NR == 1 { print $1 }')
test "$wrapper_mode" = 100755
temporary_wrapper=$(mktemp "$wrapper_parent/.admission-wrapper.XXXXXX")
trap 'rm -f -- "$temporary_wrapper"' EXIT HUP INT TERM
git -C "$TRUSTED_MAIN_CHECKOUT" show \
  "${BASE_COMMIT}:scripts/run-trusted-age-admission" \
  >"$temporary_wrapper"
chmod 0755 "$temporary_wrapper"
test -f "$temporary_wrapper"
test ! -L "$temporary_wrapper"
test ! -e "$TRUSTED_ADMISSION_WRAPPER"
test ! -L "$TRUSTED_ADMISSION_WRAPPER"
printf '%s  %s\n' "$REVIEWED_WRAPPER_SHA256" "$temporary_wrapper" |
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 --check
  else
    sha256sum --check
  fi
ln -- "$temporary_wrapper" "$TRUSTED_ADMISSION_WRAPPER"
rm -f -- "$temporary_wrapper"
temporary_wrapper=
trap - EXIT HUP INT TERM
test -f "$TRUSTED_ADMISSION_WRAPPER"
test ! -L "$TRUSTED_ADMISSION_WRAPPER"
test "$(stat -c '%a' "$TRUSTED_ADMISSION_WRAPPER" 2>/dev/null ||
  stat -f '%Lp' "$TRUSTED_ADMISSION_WRAPPER")" = 755
printf '%s  %s\n' "$REVIEWED_WRAPPER_SHA256" "$TRUSTED_ADMISSION_WRAPPER" |
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 --check
  else
    sha256sum --check
  fi
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
: "${BASE_COMMIT:?set BASE_COMMIT to the reviewed trusted base commit}"
: "${HEAD_COMMIT:?set HEAD_COMMIT to the reviewed candidate commit}"
AGE_TOOLING_DIRECTORY="$AGE_TOOLING_DIRECTORY" \
  python3 -I "$TRUSTED_ADMISSION_WRAPPER" \
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

Use Python isolated mode (`-I`) for the wrapper invocation so inherited module
search paths cannot shadow its standard-library imports.

`AGE_IDENTITY` and `ADMISSION_SIGNING_KEY` must each name a regular mode-`0600`
file outside both checkouts. `ADMISSION_RECEIPT_OUTPUT` must be a nonexistent
pathname in an existing directory outside both checkouts; use a fresh pathname
for every run because the creator rejects an existing path or symlink.

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

The initial bootstrap is a separate, immutable event-driven publisher. The
production workflow cannot evaluate the pull request that introduces it while
the App-pinned context is already required. The bootstrap publisher must run
the independently reviewed trusted-base verifier, publish the same App-owned
`Owner-signed age admission` context, and remain available through the rollback
window. It is a separate operator-owned deployment gate, not a helper embedded
in this repository's pull-request body flow.
Do not publish a check manually, mint a receipt merely to make an unprotected
transition green, push directly to `main`, edit branch protection dynamically,
or substitute an Actions check for the App context. The exact App source,
immutable bootstrap revision, protected environment, installation permissions,
and live delivery proof must be supplied through the operator deployment lane
before this workflow is activated in production. Until then, the Actions result
is advisory and the App-pinned context remains the required boundary.
Manual helper publication is forbidden.
The same deployment lane owns a tested App-key rotation, revocation, emergency,
and rollback procedure. It must name the immutable publisher retained through
the rollback window and surface any inability to publish as a fail-closed
outage, never as permission to write a manual check or edit protection.

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

## Private Catalog Editing

Edit a private catalog in a mode-`0700` temporary directory with a
mode-`0600` plaintext file. Decrypt without writing plaintext to standard
output, keep editor swap and backup files inside that phase, validate the
catalog, re-encrypt to a temporary ciphertext with the committed recipient,
and atomically replace the source ciphertext. Remove the plaintext phase on
success, failure, or interruption. Source-only catalogs have no persistent
plaintext target; never render one into the repository or another persistent
path. Catalogs with an explicit target listed above may render only to that documented mode-restricted path.

## Retiring The Daybreak Catalog

`chezmoi apply` does not prune a private target when its source is removed or
rolled back. Under explicit operator authorization for this exact target, first
verify that `~/.agents/daybreak-account-bindings.md` is a regular mode-`0600`
file and not a symlink, then remove only that path and verify that it is absent:

```zsh
set -eu
target="$HOME/.agents/daybreak-account-bindings.md"
parent="${target:h}"
if [[ ! -d "$parent" || -L "$parent" || ! -f "$target" || -L "$target" ]]; then
  print -u2 -- 'refusing exact-target cleanup'
  exit 1
fi
case "$(uname -s)" in
Darwin)
  mode="$(stat -f '%Lp' "$target")"
  owner="$(stat -f '%u' "$target")"
  ;;
Linux)
  mode="$(stat -c '%a' -- "$target")"
  owner="$(stat -c '%u' -- "$target")"
  ;;
*)
  print -u2 -- 'refusing exact-target cleanup on an unsupported platform'
  exit 1
  ;;
esac
if [[ "$mode" != 600 || "$owner" != "$EUID" ]]; then
  print -u2 -- 'refusing exact-target cleanup for an unexpected owner or mode'
  exit 1
fi
rm -- "$target"
test ! -e "$target" && test ! -L "$target"
```

Perform that exact-target cleanup before removing or reverting the encrypted
catalog and its template. Never use a recursive cleanup or infer a target from
decrypted catalog contents. Re-apply only after the authorized source change is
complete and the target has been re-verified.

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
