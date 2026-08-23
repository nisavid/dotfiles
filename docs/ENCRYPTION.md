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

The workflow contains the legacy-protected `owner-signed-age-v1` activation
sentinel. Keep that marker in every admitted workflow revision; the gate rejects
an active transition that removes it, so recovery cannot silently fall back to
the pre-bootstrap path.

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
Use a freshly created, private mode-`0700` wrapper directory; the launcher also
rejects any group/world-writable or foreign-owned ancestor at invocation time.

For the one-time bootstrap, freeze concurrent `main` merges, set
`BOOTSTRAP_ADMISSION=1`, and run this preflight against the refreshed live
base. A nonzero result is a hard stop; do not authorize the bootstrap exception.

```zsh
set -euo pipefail
: "${TRUSTED_MAIN_CHECKOUT:?set TRUSTED_MAIN_CHECKOUT to the trusted checkout}"
: "${BASE_COMMIT:?set BASE_COMMIT to the refreshed trusted base commit}"
test "${BOOTSTRAP_ADMISSION:-0}" = 1
test "$(git -C "$TRUSTED_MAIN_CHECKOUT" rev-parse --verify HEAD)" = "$BASE_COMMIT"
git -C "$TRUSTED_MAIN_CHECKOUT" rev-parse --verify "${BASE_COMMIT}^{commit}" >/dev/null
origin_url=$(git -C "$TRUSTED_MAIN_CHECKOUT" remote get-url origin)
case "$origin_url" in
  git'@'github.com:nisavid/dotfiles.git|https://github.com/nisavid/dotfiles.git) ;;
  *)
    printf 'origin is not nisavid/dotfiles: %s\n' "$origin_url" >&2
    exit 1
    ;;
esac
remote_base=$(git -C "$TRUSTED_MAIN_CHECKOUT" ls-remote --exit-code origin refs/heads/main | awk '{ print $1 }')
test "$remote_base" = "$BASE_COMMIT"
git -C "$TRUSTED_MAIN_CHECKOUT" cat-file -e \
  "${BASE_COMMIT}:.github/workflows/privacy-age-integrity.yml"
if git -C "$TRUSTED_MAIN_CHECKOUT" cat-file blob \
  "${BASE_COMMIT}:.github/workflows/privacy-age-integrity.yml" | grep -Fqx \
  '# Protected admission activation sentinel: owner-signed-age-v1'; then
  printf 'activation sentinel is already present in the trusted base\n' >&2
  exit 1
fi
for bootstrap_path in \
  .github/age-admission/allowed_signers \
  scripts/create-age-admission-receipt \
  scripts/run-trusted-age-admission \
  scripts/privacy_age_admission.py; do
  if git -C "$TRUSTED_MAIN_CHECKOUT" cat-file -e "${BASE_COMMIT}:$bootstrap_path" 2>/dev/null; then
    printf 'bootstrap path already exists in the trusted base: %s\n' "$bootstrap_path" >&2
    exit 1
  fi
done
```

Before changing any protection rule, run this independent bootstrap-tree check
from a separately reviewed copy of the candidate branch. The old `main`
workflow cannot run the new candidate gate yet, so this owner-side check is a
required part of the one-time exception. It compares the complete protected
diff, object kinds and modes, the reviewed signer blob and fingerprint, and the
activation marker. Keep only the final digest and fingerprint in the operator
ledger; the command never prints file contents.

Run it only after the pull request exists and refresh the pull-request API (or
the public pull ref) immediately beforehand. The candidate checkout and the
pull-request head must be the same immutable commit; a locally reviewed commit
that is not the live pull-request head is not eligible for the exception.

Supply `REVIEWED_BOOTSTRAP_MANIFEST` as a newly created, mode-`0600` file
outside both checkouts. Populate it from an independent review of the
immutable pull-request head, not from the candidate document. Use one tab-
separated `path`, `mode`, `kind`, `object-id` row for each expected path, plus
`tree_sha256` and `signer_fingerprint` metadata rows. The check below compares
the candidate to that detached manifest and fails if the reviewed digest is
not supplied.

Its shape is:

```text
path<TAB>mode<TAB>kind<TAB>object-id
tree_sha256<TAB>sha256<TAB><digest>
signer_fingerprint<TAB>sha256<TAB>SHA256:<fingerprint>
```

The detached manifest is UTF-8 text terminated by one trailing newline. A
newline-free final record is malformed and must be regenerated before the
preflight is rerun.

Generate the path rows and the digest from the immutable reviewed head with
`git ls-tree -r -z`; then independently review the resulting rows before
making the file mode `0600`. Do not generate the manifest from a mutable
checkout or from this document.

```zsh
set -euo pipefail
: "${TRUSTED_MAIN_CHECKOUT:?set TRUSTED_MAIN_CHECKOUT to the trusted checkout}"
: "${BOOTSTRAP_CHECKOUT:?set BOOTSTRAP_CHECKOUT to the candidate checkout}"
: "${BASE_COMMIT:?set BASE_COMMIT to the refreshed live main commit}"
: "${HEAD_COMMIT:?set HEAD_COMMIT to the reviewed bootstrap commit}"
: "${BOOTSTRAP_PR_NUMBER:?set BOOTSTRAP_PR_NUMBER to the bootstrap pull request number}"
: "${BOOTSTRAP_PR_HEAD_OWNER:?set BOOTSTRAP_PR_HEAD_OWNER to the reviewed head owner}"
: "${BOOTSTRAP_PR_HEAD_BRANCH:?set BOOTSTRAP_PR_HEAD_BRANCH to the reviewed head branch}"
[[ "$BOOTSTRAP_PR_NUMBER" =~ ^[0-9]+$ ]]
test "$(git -C "$TRUSTED_MAIN_CHECKOUT" rev-parse --verify HEAD)" = "$BASE_COMMIT"
test "$(git -C "$BOOTSTRAP_CHECKOUT" rev-parse --verify HEAD)" = "$HEAD_COMMIT"
git -C "$BOOTSTRAP_CHECKOUT" merge-base --is-ancestor "$BASE_COMMIT" "$HEAD_COMMIT"
pr_api_path="repos/nisavid/dotfiles/pulls/${BOOTSTRAP_PR_NUMBER}"
pr_snapshot=$(gh api --repo nisavid/dotfiles "$pr_api_path" --jq \
  '[.state, .base.ref, .base.sha, .head.repo.full_name, .head.user.login, .head.ref, .head.sha] | @tsv')
IFS=$'\t' read -r pr_state pr_base_ref pr_base_sha pr_head_repo \
  pr_head_owner pr_head_branch pr_head_sha <<<"$pr_snapshot"
test "$pr_state" = open
test "$pr_base_ref" = main
test "$pr_base_sha" = "$BASE_COMMIT"
test "$pr_head_repo" = nisavid/dotfiles
test "$pr_head_owner" = "$BOOTSTRAP_PR_HEAD_OWNER"
test "$pr_head_branch" = "$BOOTSTRAP_PR_HEAD_BRANCH"
test "$pr_head_sha" = "$HEAD_COMMIT"
pr_head=$(git -C "$TRUSTED_MAIN_CHECKOUT" ls-remote --exit-code origin \
  "refs/pull/${BOOTSTRAP_PR_NUMBER}/head" | awk '{ print $1 }')
test "$pr_head" = "$HEAD_COMMIT"
trusted_root=$(cd -P -- "$TRUSTED_MAIN_CHECKOUT" && pwd)
bootstrap_root=$(cd -P -- "$BOOTSTRAP_CHECKOUT" && pwd)

bootstrap_tmp=$(mktemp -d "${TMPDIR:-/tmp}/age-bootstrap-check.XXXXXX")
trap 'rm -rf -- "$bootstrap_tmp"' EXIT HUP INT TERM
expected_paths="$bootstrap_tmp/expected"
actual_paths="$bootstrap_tmp/actual"
all_paths="$bootstrap_tmp/all"
unexpected_paths="$bootstrap_tmp/unexpected"
cat >"$expected_paths" <<'EOF'
.github/age-admission/allowed_signers
.github/workflows/platform-portability.yml
.github/workflows/privacy-age-integrity.yml
docs/ENCRYPTION.md
scripts/admit-age-envelopes
scripts/privacy-scan
scripts/create-age-admission-receipt
scripts/privacy_age_admission.py
scripts/privacy_age_envelopes.py
scripts/privacy_age_integrity_gate.py
scripts/run-trusted-age-admission
docs/adr/0001-owner-signed-age-admission.md
tests/platform-portability.zsh
tests/test_privacy_age_admission.py
tests/test_privacy_age_envelopes.py
tests/test_privacy_age_integrity_gate.py
EOF
LC_ALL=C sort -o "$expected_paths" "$expected_paths"
git -C "$BOOTSTRAP_CHECKOUT" --no-pager diff --no-ext-diff --no-textconv \
  --name-only --no-renames \
  "$BASE_COMMIT" "$HEAD_COMMIT" >"$all_paths"
: >"$actual_paths"
: >"$unexpected_paths"
# Compare the complete changed-path set against the same explicit allowlist
# used for the detached manifest. Every unlisted path, including protected
# collateral, is unexpected.
LC_ALL=C grep -Fxf "$expected_paths" "$all_paths" >"$actual_paths" || :
LC_ALL=C grep -Fxvf "$expected_paths" "$all_paths" >"$unexpected_paths" || :
LC_ALL=C sort -o "$actual_paths" "$actual_paths"
test ! -s "$unexpected_paths"
cmp -s "$expected_paths" "$actual_paths"
: "${REVIEWED_BOOTSTRAP_MANIFEST:?set REVIEWED_BOOTSTRAP_MANIFEST to the detached reviewed manifest}"
manifest_parent=$(cd -P -- "$(dirname -- "$REVIEWED_BOOTSTRAP_MANIFEST")" && pwd)
manifest_path="$manifest_parent/$(basename -- "$REVIEWED_BOOTSTRAP_MANIFEST")"
test -f "$manifest_path"
test ! -L "$manifest_path"
manifest_mode=$(stat -c '%a' "$manifest_path" 2>/dev/null ||
  stat -f '%Lp' "$manifest_path")
manifest_uid=$(stat -c '%u' "$manifest_path" 2>/dev/null ||
  stat -f '%u' "$manifest_path")
manifest_size=$(stat -c '%s' "$manifest_path" 2>/dev/null ||
  stat -f '%z' "$manifest_path")
test "$manifest_mode" = 600
test "$manifest_uid" = "$(id -u)"
test "$manifest_size" -le 65536
manifest_parent_mode=$(stat -c '%a' "$manifest_parent" 2>/dev/null ||
  stat -f '%Lp' "$manifest_parent")
manifest_parent_uid=$(stat -c '%u' "$manifest_parent" 2>/dev/null ||
  stat -f '%u' "$manifest_parent")
test "$manifest_parent_mode" = 700
test "$manifest_parent_uid" = "$(id -u)"
case "$manifest_path" in
  "$trusted_root"/*|"$bootstrap_root"/*)
    printf 'bootstrap manifest must be outside both checkouts\n' >&2
    exit 1
    ;;
esac
manifest_paths="$bootstrap_tmp/manifest-paths"
manifest_sorted="$bootstrap_tmp/manifest-sorted"
manifest_tree_digest=
manifest_signer_fingerprint=
: >"$manifest_paths"
while IFS=$'\t' read -r manifest_entry_path mode kind object extra; do
  [[ -z "$manifest_entry_path" || "$manifest_entry_path" == \#* ]] && continue
  case "$manifest_entry_path" in
    tree_sha256)
      test -z "$manifest_tree_digest"
      test "$mode" = sha256
      test -n "$kind"
      test -z "$object"
      manifest_tree_digest=$kind
      ;;
    signer_fingerprint)
      test -z "$manifest_signer_fingerprint"
      test "$mode" = sha256
      test -n "$kind"
      test -z "$object"
      manifest_signer_fingerprint=$kind
      ;;
    *)
      test -z "$extra"
      [[ "$mode" =~ ^100(644|755)$ ]]
      test "$kind" = blob
      [[ "$object" =~ ^[0-9a-f]{40}$ ]]
      printf '%s\n' "$manifest_entry_path" >>"$manifest_paths"
      metadata=$(git -C "$BOOTSTRAP_CHECKOUT" ls-tree "$HEAD_COMMIT" -- "$manifest_entry_path" |
        awk -F '\t' 'NF == 2 { print $1 }')
      read -r actual_mode actual_kind actual_object <<EOF
$metadata
EOF
      test "$actual_mode" = "$mode"
      test "$actual_kind" = "$kind"
      test "$actual_object" = "$object"
      ;;
  esac
done <"$manifest_path"
test -n "$manifest_tree_digest"
test -n "$manifest_signer_fingerprint"
LC_ALL=C sort "$manifest_paths" >"$manifest_sorted"
test -z "$(uniq -d "$manifest_sorted")"
cmp -s "$expected_paths" "$manifest_sorted"

for bootstrap_path in \
  .github/age-admission/allowed_signers \
  scripts/create-age-admission-receipt \
  scripts/run-trusted-age-admission \
  scripts/privacy_age_admission.py; do
  if git -C "$TRUSTED_MAIN_CHECKOUT" ls-tree -r --name-only "$BASE_COMMIT" -- "$bootstrap_path" |
    grep -Fqx "$bootstrap_path"; then
    printf 'bootstrap path already exists in trusted base: %s\n' "$bootstrap_path" >&2
    exit 1
  fi
done
workflow_object=$(git -C "$BOOTSTRAP_CHECKOUT" ls-tree "$HEAD_COMMIT" -- \
  .github/workflows/privacy-age-integrity.yml | awk -F '\t' 'NF == 2 { print $1 }' | awk '{ print $3 }')
git -C "$BOOTSTRAP_CHECKOUT" cat-file blob "$workflow_object" |
  grep -Fqx '# Protected admission activation sentinel: owner-signed-age-v1'
signer_object=$(git -C "$BOOTSTRAP_CHECKOUT" ls-tree "$HEAD_COMMIT" -- \
  .github/age-admission/allowed_signers | awk -F '\t' 'NF == 2 { print $1 }' | awk '{ print $3 }')
git -C "$BOOTSTRAP_CHECKOUT" cat-file blob "$signer_object" >"$bootstrap_tmp/allowed_signers"
awk '!/^[[:space:]]*#/ && NF >= 3 {
  for (i = 2; i < NF; i++)
    if ($i ~ /^(ssh-|ecdsa-|sk-ssh-|sk-ecdsa-)/) {
      print $i, $(i + 1)
      count++
      break
    }
} END { exit count != 1 }' \
  "$bootstrap_tmp/allowed_signers" >"$bootstrap_tmp/allowed_signers.pub"
test "$(ssh-keygen -lf "$bootstrap_tmp/allowed_signers.pub" -E sha256 | awk 'NR == 1 { print $2 }')" = \
  "$manifest_signer_fingerprint"
tree_digest=$(git -C "$BOOTSTRAP_CHECKOUT" ls-tree -r -z "$HEAD_COMMIT" -- \
  .github/age-admission/allowed_signers \
  .github/workflows/platform-portability.yml \
  .github/workflows/privacy-age-integrity.yml \
  docs/ENCRYPTION.md \
  scripts/admit-age-envelopes \
  scripts/privacy-scan \
  scripts/create-age-admission-receipt \
  scripts/privacy_age_admission.py \
  scripts/privacy_age_envelopes.py \
  scripts/privacy_age_integrity_gate.py \
  scripts/run-trusted-age-admission \
  docs/adr/0001-owner-signed-age-admission.md \
  tests/platform-portability.zsh \
  tests/test_privacy_age_admission.py \
  tests/test_privacy_age_envelopes.py \
  tests/test_privacy_age_integrity_gate.py |
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | awk '{ print $1 }'
  else
    sha256sum | awk '{ print $1 }'
  fi)
test "$tree_digest" = "$manifest_tree_digest"
printf 'bootstrap-tree=%s signer-fingerprint=%s\n' \
  "$tree_digest" "$manifest_signer_fingerprint"
```

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

The first bootstrap of this boundary is a one-time exception: the trusted
base predates the signer and verifier paths, so it cannot verify a v1 receipt.
Freeze other `main` merges while the exception is open and, immediately before
the break-glass action, verify from the live base commit that none of the four
new admission pathnames already exists. A pre-seeded placeholder would be
trusted by the legacy pre-bootstrap gate, so the owner must compare the exact
bootstrap tree and branch-protection preimage before authorizing this one
transition. The current protection rule does not require this workflow's
context, so keep `main` owner-frozen throughout the preflight and exception;
the sentinel is a defense against accidental activation, not an automated
replacement for that freeze.
Create the bootstrap branch from `main` and open its pull request targeting
`main`. The branch must contain and replace every new admission infrastructure
path before the exception is used: the signer, external launcher wrapper,
creator, admission module, legacy admitter, envelope helper, privacy scanner,
trusted gate, and boundary workflow. It must retain the trusted classifier
unchanged because the scanner imports that base-owned helper. Keep its review
and required checks visible. Classic GitHub branch
protection has no per-pull-request, branch-scoped bypass; if the owner
authorizes this exception, record the exact live protection-rule preimage,
freeze concurrent `main` merges, apply only the temporary narrowly scoped rule
change needed for this named pull request, and restore the preimage immediately
after the merge. Never push directly to `main`, disable unrelated protections,
or reuse the exception for ordinary changes. Re-enable the protection
immediately, verify that `main` contains the signer and verifier paths, and
record the exact Checks API `name` emitted by the job — currently
`Verify trusted base against candidate data` (the UI may render it with the
workflow name prefixed). Read that name from a fresh check run. Do not treat
that Actions job name as the final authenticated admission requirement; verify
the dedicated App-pinned context described below through the live
branch-protection API before creating a receipt for the next protected pull
request.

The protection preimage is an operator-owned break-glass artifact, not a value
to infer from this document. Immediately before any temporary rule edit, read
the live `main` protection through the GitHub API, save the exact response and
its SHA-256 outside both checkouts, pause auto-merge, and verify that no other
merge actor is proceeding. Re-read the rule and the named pull request after
the freeze; if either digest or head SHA changed, stop. Apply only the
pre-authorized narrow change, merge the named pull request, restore the saved
protection fields immediately using an explicitly allowlisted update payload
derived from the preimage (never replay read-only GET fields verbatim), and
compare a fresh post-restore response to the preimage before releasing the
freeze. Repeat the one-snapshot pull-request binding and public head-ref check
immediately before the protection API update; the earlier manifest result is
not reusable after any state change. A failed or ambiguous restore is an
incident gate: do not continue with another merge or live apply.

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
