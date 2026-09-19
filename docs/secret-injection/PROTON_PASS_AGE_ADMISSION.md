# Sign age admissions and recover a lost signer

Use this procedure to create an owner admission receipt with the dedicated
passphraseless SSH Ed25519 key held in Proton Pass, or to replace that key when
the private half of the signer already trusted by `main` is unavailable.

The key delegates the trusted user session's signing authority to an agent on
an authorized personal host. Its signature does not prove that the owner
personally reviewed the change, and it does not independently force validation
to run. Review, the trusted-base receipt creator, hosted checks, conversation
resolution, and branch protection remain separate gates.

This is a post-bootstrap procedure. A candidate cannot authorize its own key,
ordinary rotation requires the current private signer, and the initial
bootstrap exception is not a lost-key mechanism. Do not restore the retired
admission App or transition-bundle design.

## Bind the procedure to reviewed source

Issue [#286](https://github.com/nisavid/dotfiles/issues/286) owns this
procedure and its implementation. Before production use, its operational
handoff must record all of these value-free facts:

- the immutable, reviewed source commit published by the coordinator;
- the SHA-256 of
  `home/private_dot_local/bin/executable_proton-pass-age-admission` at that
  commit;
- the SHA-256 of `scripts/run-trusted-age-admission` used by that revision;
- the SHA-256 of `scripts/create-age-admission-receipt` used by that revision;
- the accepted public signer fingerprint and the source/test results; and
- the admission-specific live-provider qualification result.

A consumer must use that published source revision, not a mutable branch or a
locally edited copy, and must require its reviewed adapter blob to equal the
blob in the current trusted base. This remains valid across a squash merge,
which publishes the reviewed bytes under a different commit topology. A change
to the adapter, readiness route, receipt creator, integrity gate, trusted
wrapper, provider behavior, or accepted signer makes the affected review and
evidence stale. Stable Proton Pass share and item IDs are private operation
inputs; do not put them in this document, a pull request, or a public issue
comment.

The provider-free classifier is part of both the trusted wrapper and receipt
creator. Any revision that adds or changes it requires fresh wrapper and
creator digests; a handoff from before that revision is stale.

The adapter supports one input shape:

- Linux or macOS in an authorized trusted user session;
- a custom item selected by stable share ID and item ID, each matching
  `[A-Za-z0-9_-]{1,128}`;
- the hidden field `SSH.private_key` only;
- one unencrypted OpenSSH Ed25519 private key no larger than 64 KiB;
- a pinned `SHA256:...` SSH public fingerprint;
- lowercase 40-character base and head commit IDs; and
- an unused receipt-output path outside both checkouts.

It calls `pass-cli item view` for only that field with human output, using the
same `proton-pass-ensure-ready` route as `secret-exec`. It removes an inherited
Proton bootstrap token before starting provider or receipt children. Current
source selects the D-Bus keyring on Linux and the platform default on macOS. It
gives readiness 45 seconds, provider retrieval 3 seconds, key validation 15
seconds, and receipt creation 180 seconds by default with a 300-second maximum.
Real-provider qualification must confirm that the selected CLI returns only
the field bytes and its final line terminator for this item shape.

Before readiness or provider access, the adapter invokes the trusted launcher's
`--operation preflight` branch with only the exact base/head checkouts and
commits. The trusted creator loads its integrity classifier from raw trusted-
base blobs and emits exactly one of three results: exit `0` with `required`,
exit `10` with `not-required`, or exit `11` with `indeterminate`. The adapter
accepts only the exact bytes `required\n` with exit `0`; all three classified
results have empty standard error. Every other status, output, or diagnostic
stops before readiness and `pass-cli`.

## Entry conditions for routine signing

Before the provider-free preflight:

1. The task names one pull request and authorizes transition classification
   plus receipt creation if required. Routine signing on a qualified trusted
   host does not require a key passphrase, owner confirmation, or YubiKey touch.
2. Issue #286 identifies the reviewed published source revision and the current
   adapter, trusted-wrapper, and creator digests.
3. The pull request is open against `main`; its current base and head commits
   are frozen for this run and are present in clean local checkouts. The trusted
   creator checks tracked, untracked, and ignored entries itself.
4. The trusted base contains the activation sentinel, reviewed trusted wrapper,
   creator, integrity classifier, and existing v1 verifier.
5. A new mode-`0700` operation directory can be kept outside both checkouts.

Exit `10` with exact output `not-required\n` and empty standard error is a
successful routine no-op: remove the operation directory and stop without
loading provider inputs. Exit `11` with `indeterminate\n` and empty standard
error, any malformed result, or any wrapper, argument, or trust failure is a
hard stop with provider access untouched.

Only the exact pair exit `0` and `required\n` permits the provider phase. Before
that phase:

1. Admission-specific live-provider qualification has passed on the current
   enrollment. Source fixtures alone are not production qualification.
2. The trusted base contains the accepted public key and reviewed adapter
   source in addition to the preflight paths above.
3. The machine-local age identity is a mode-`0600` regular file outside both
   checkouts, and `AGE_TOOLING_DIRECTORY` selects checksum-verified age v1.3.1
   tools outside both checkouts.
4. The installed adapter and readiness helper are regular, non-symlinked
   executables under `$HOME/.local/bin`. The adapter bytes equal the reviewed
   source bytes.
5. The operation-directory filesystem permits execution of the creator's
   private staged `ssh-keygen` copy on Linux.

## Create a receipt

### Freeze and verify the exact transition

Set only the inputs needed to classify the transition from the reviewed
handoff and fresh pull-request state:

```zsh
set -euo pipefail
: "${PR_NUMBER:?set the pull request number}"
: "${TRUSTED_MAIN_CHECKOUT:?set the trusted main checkout}"
: "${CANDIDATE_CHECKOUT:?set the candidate checkout}"
: "${BASE_COMMIT:?set the pull request's current base commit}"
: "${HEAD_COMMIT:?set the pull request's current head commit}"
: "${REVIEWED_WRAPPER_SHA256:?set the reviewed wrapper SHA-256}"
: "${ADMISSION_PRIVATE_PARENT:?set an external private temporary parent}"

REPOSITORY=nisavid/dotfiles
```

Read the pull request once, bind both local checkouts and both public refs to
that snapshot, and require a linear candidate:

```zsh
pr_snapshot=$(gh api "repos/$REPOSITORY/pulls/$PR_NUMBER")
test "$(jq -r .state <<<"$pr_snapshot")" = open
test "$(jq -r .base.ref <<<"$pr_snapshot")" = main
test "$(jq -r .base.sha <<<"$pr_snapshot")" = "$BASE_COMMIT"
test "$(jq -r .head.repo.full_name <<<"$pr_snapshot")" = "$REPOSITORY"
test "$(jq -r .head.sha <<<"$pr_snapshot")" = "$HEAD_COMMIT"

test "$(git -C "$TRUSTED_MAIN_CHECKOUT" rev-parse --verify HEAD)" = \
  "$BASE_COMMIT"
test "$(git -C "$CANDIDATE_CHECKOUT" rev-parse --verify HEAD)" = \
  "$HEAD_COMMIT"
test "$(git -C "$TRUSTED_MAIN_CHECKOUT" ls-remote --exit-code origin \
  refs/heads/main | awk 'NR == 1 { print $1 }')" = "$BASE_COMMIT"
test "$(git -C "$TRUSTED_MAIN_CHECKOUT" ls-remote --exit-code origin \
  "refs/pull/$PR_NUMBER/head" | awk 'NR == 1 { print $1 }')" = "$HEAD_COMMIT"
git -C "$CANDIDATE_CHECKOUT" merge-base --is-ancestor \
  "$BASE_COMMIT" "$HEAD_COMMIT"

test -z "$(git -C "$TRUSTED_MAIN_CHECKOUT" status --porcelain=v1 \
  --untracked-files=all --ignored=matching)"
test -z "$(git -C "$CANDIDATE_CHECKOUT" status --porcelain=v1 \
  --untracked-files=all --ignored=matching)"
```

The status checks above are an operator preflight. The trusted creator still
performs its own raw Git-object, index, worktree, and ignored-entry validation;
do not weaken or replace that check.

### Prepare the bounded external phase

Create one private operation directory. Keep the shell open through receipt
publication so the exit trap can remove the receipt, wrapper, public-key copy,
and any failed private staging:

```zsh
file_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}
file_uid() {
  stat -c '%u' "$1" 2>/dev/null || stat -f '%u' "$1"
}
file_sha256() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk 'NR == 1 { print $1 }'
  else
    sha256sum "$1" | awk 'NR == 1 { print $1 }'
  fi
}

private_parent=$(cd -P -- "$ADMISSION_PRIVATE_PARENT" && pwd)
test -d "$private_parent"
test ! -L "$ADMISSION_PRIVATE_PARENT"
test "$(file_mode "$private_parent")" = 700
test "$(file_uid "$private_parent")" = "$EUID"

trusted_root=$(cd -P -- "$TRUSTED_MAIN_CHECKOUT" && pwd)
candidate_root=$(cd -P -- "$CANDIDATE_CHECKOUT" && pwd)
case "$private_parent/" in
  "$trusted_root/"*|"$candidate_root/"*)
    print -u2 -- 'private temporary parent is inside a checkout'
    exit 1
    ;;
esac

operation_dir=$(mktemp -d "$private_parent/proton-pass-age-admission.XXXXXX")
chmod 0700 "$operation_dir"
test ! -L "$operation_dir"
test "$(file_mode "$operation_dir")" = 700
test "$(file_uid "$operation_dir")" = "$EUID"

cleanup_operation() {
  if [[ -n ${operation_dir:-} ]]; then
    case "$operation_dir" in
      "$private_parent"/proton-pass-age-admission.*)
        if [[ -d "$operation_dir" && ! -L "$operation_dir" ]]; then
          rm -rf -- "$operation_dir"
        fi
        ;;
      *) print -u2 -- 'refusing unexpected operation-directory cleanup' ;;
    esac
  fi
}
trap cleanup_operation EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
```

Materialize the trusted wrapper from the exact base, rather than either live
checkout's pathname, and compare it with its reviewed digest:

```zsh
wrapper_source=scripts/run-trusted-age-admission
wrapper_record=$(git -C "$TRUSTED_MAIN_CHECKOUT" ls-tree \
  "$BASE_COMMIT" -- "$wrapper_source")
test -n "$wrapper_record"
test "${wrapper_record%% *}" = 100755
wrapper_object=${${wrapper_record#* }#* }
wrapper_object=${wrapper_object%%$'\t'*}
trusted_wrapper=$operation_dir/run-trusted-age-admission
git -C "$TRUSTED_MAIN_CHECKOUT" cat-file blob "$wrapper_object" \
  >"$trusted_wrapper"
chmod 0755 "$trusted_wrapper"
test "$(file_sha256 "$trusted_wrapper")" = "$REVIEWED_WRAPPER_SHA256"
```

Run the trusted provider-free classifier and compare both its status and exact
output. The successful no-op branch removes the private operation directory
without loading any Proton Pass or signer inputs:

```zsh
preflight_output=$operation_dir/preflight.out
preflight_error=$operation_dir/preflight.err
preflight_rc=0
if TMPDIR="$operation_dir" \
  python3 -I -B -S "$trusted_wrapper" \
    --base-repository "$TRUSTED_MAIN_CHECKOUT" \
    --base-commit "$BASE_COMMIT" -- \
    --operation preflight \
    --base-repository "$TRUSTED_MAIN_CHECKOUT" \
    --base-commit "$BASE_COMMIT" \
    --head-repository "$CANDIDATE_CHECKOUT" \
    --head-commit "$HEAD_COMMIT" \
    >"$preflight_output" 2>"$preflight_error"; then
  preflight_rc=0
else
  preflight_rc=$?
fi

if (( preflight_rc == 0 )) && [[ ! -s "$preflight_error" ]] &&
  printf 'required\n' | cmp -s - "$preflight_output"; then
  :
elif (( preflight_rc == 10 )) && [[ ! -s "$preflight_error" ]] &&
  printf 'not-required\n' | cmp -s - "$preflight_output"; then
  cleanup_operation
  operation_dir=
  trap - EXIT HUP INT TERM
  print -r -- 'age admission is not required for this transition'
  exit 0
else
  print -u2 -- 'age-admission preflight is indeterminate'
  exit 1
fi
```

Only after the exact `required` result, load the private provider binding and
signing inputs. Bind the installed adapter to the reviewed published bytes and
require the trusted base to carry the same source blob:

```zsh
: "${PROCEDURE_REVISION:?set the reviewed published revision from issue 286}"
: "${REVIEWED_ADAPTER_SHA256:?set the reviewed adapter SHA-256}"
: "${PROTON_PASS_SHARE_ID:?set the private stable share ID}"
: "${PROTON_PASS_ITEM_ID:?set the private stable item ID}"
: "${EXPECTED_SIGNER_FINGERPRINT:?set the pinned public fingerprint}"
: "${AGE_IDENTITY:?set the external mode-0600 age identity}"
: "${AGE_TOOLING_DIRECTORY:?set the verified external age-tool directory}"

ADMISSION_ADAPTER=$HOME/.local/bin/proton-pass-age-admission
ADMISSION_READINESS=$HOME/.local/bin/proton-pass-ensure-ready
adapter_source=home/private_dot_local/bin/executable_proton-pass-age-admission
git -C "$TRUSTED_MAIN_CHECKOUT" cat-file -e \
  "${PROCEDURE_REVISION}^{commit}"
reviewed_adapter=$(git -C "$TRUSTED_MAIN_CHECKOUT" ls-tree \
  "$PROCEDURE_REVISION" -- "$adapter_source")
base_adapter=$(git -C "$TRUSTED_MAIN_CHECKOUT" ls-tree \
  "$BASE_COMMIT" -- "$adapter_source")
test -n "$reviewed_adapter"
test "$reviewed_adapter" = "$base_adapter"
test "${reviewed_adapter%% *}" = 100644
adapter_object=${${reviewed_adapter#* }#* }
adapter_object=${adapter_object%%$'\t'*}
git -C "$TRUSTED_MAIN_CHECKOUT" cat-file blob "$adapter_object" \
  >"$operation_dir/reviewed-adapter"
test "$(file_sha256 "$operation_dir/reviewed-adapter")" = \
  "$REVIEWED_ADAPTER_SHA256"
test -f "$ADMISSION_ADAPTER"
test ! -L "$ADMISSION_ADAPTER"
test -x "$ADMISSION_ADAPTER"
test "$(file_mode "$ADMISSION_ADAPTER")" = 755
test "$(file_uid "$ADMISSION_ADAPTER")" = "$EUID"
cmp -s "$operation_dir/reviewed-adapter" "$ADMISSION_ADAPTER"
test -f "$ADMISSION_READINESS"
test ! -L "$ADMISSION_READINESS"
test -x "$ADMISSION_READINESS"
test "$(file_mode "$ADMISSION_READINESS")" = 755
test "$(file_uid "$ADMISSION_READINESS")" = "$EUID"
```

Extract only the public key from the trusted base's one allowed-signer record
and compare its fingerprint with the independently pinned value:

```zsh
git -C "$TRUSTED_MAIN_CHECKOUT" cat-file blob \
  "$BASE_COMMIT:.github/age-admission/allowed_signers" \
  >"$operation_dir/allowed_signers"
awk '
  /^[[:space:]]*(#|$)/ { next }
  {
    count++
    if (NF < 4 || $1 != "repository-owner" ||
        $2 != "namespaces=\"nisavid/dotfiles/age-admission/v1\"" ||
        $3 != "ssh-ed25519") exit 2
    print $3, $4
  }
  END { if (count != 1) exit 1 }
' "$operation_dir/allowed_signers" >"$operation_dir/allowed_signer.pub"
actual_fingerprint=$(ssh-keygen -lf "$operation_dir/allowed_signer.pub" \
  -E sha256 | awk 'NR == 1 { print $2 }')
test "$actual_fingerprint" = "$EXPECTED_SIGNER_FINGERPRINT"
```

### Retrieve, validate, and sign

Invoke the adapter with identifiers, paths, and public values only. The private
key travels from the selected provider field into the adapter's exclusive
mode-`0600` file. It is never placed in an argument, environment variable,
checkout file, log, or output. The adapter reruns the same trusted preflight
immediately before readiness and permits provider access only for its exact
`required` result:

```zsh
receipt=$operation_dir/receipt.marker
TMPDIR="$operation_dir" \
AGE_TOOLING_DIRECTORY="$AGE_TOOLING_DIRECTORY" \
python3 -I -B -S "$ADMISSION_ADAPTER" \
  --share-id "$PROTON_PASS_SHARE_ID" \
  --item-id "$PROTON_PASS_ITEM_ID" \
  --expected-fingerprint "$EXPECTED_SIGNER_FINGERPRINT" \
  --trusted-launcher "$trusted_wrapper" \
  --base-repository "$TRUSTED_MAIN_CHECKOUT" \
  --base-commit "$BASE_COMMIT" \
  --head-repository "$CANDIDATE_CHECKOUT" \
  --head-commit "$HEAD_COMMIT" \
  --repository "$REPOSITORY" \
  --identity "$AGE_IDENTITY" \
  --trusted-admitter "$TRUSTED_MAIN_CHECKOUT/scripts/admit-age-envelopes" \
  --output "$receipt"
```

The trusted wrapper checks its raw base blob and the live base copy, then runs
only the verified creator blob. The creator independently checks both clean
checkouts, materializes the trusted and candidate trees, performs identity-
backed `--check-only` age admission, preserves the
`privacy-age-admission/v1` namespace, principal, payload, expiry, and exact
base/head path binding, and signs only after validation succeeds.

Require the secret-free receipt and the complete removal of the adapter's
retrieved-key directory and the creator's nested tree, signer, key, and payload
staging before using the result:

```zsh
test -f "$receipt"
test ! -L "$receipt"
test "$(file_mode "$receipt")" = 600
test "$(file_uid "$receipt")" = "$EUID"
test "$(wc -l <"$receipt")" -eq 1
test "$(wc -c <"$receipt")" -le 65537
test -z "$(find "$operation_dir" -mindepth 1 -maxdepth 1 \
  -type d -print -quit)"
test ! -e "$operation_dir/signing-key"
test ! -L "$operation_dir/signing-key"
```

Use `publishing-reviewable-prs` for the separately authorized pull-request body
edit. Replace any earlier `privacy-age-admission/v1` marker with the one exact
line in `receipt`; never add a second marker. Editing the body triggers the
trusted hosted check. Confirm that the check used the same base and head, then
trigger and observe a fresh run immediately before merge. A changed base or
head invalidates the receipt. Wall-clock expiry does not retract a previously
successful GitHub check.

After the marker is published and staging absence is verified, remove the
operation directory in the same shell:

```zsh
cleanup_operation
operation_dir=
trap - EXIT HUP INT TERM
```

### Failure and interruption branches

- Provider unreadiness, unavailable/empty data, malformed or encrypted key
  data, a mismatched fingerprint, truncation, more than 64 KiB, invalid inputs,
  a dirty checkout, failed age validation, signing failure, timeout, an
  existing output path, or a missing, empty, loose-mode, multi-link, or
  oversized receipt fails closed. The adapter emits only
  `proton-pass age admission failed` and creates no usable receipt. It uses the
  same failure result when child retirement, output removal, or private-root
  cleanup is incomplete or cannot be verified; any surviving root or output
  remains non-authoritative evidence.
- `HUP`, `INT`, and `TERM` are catchable. The first signal fixes the eventual
  `128 + signal` status; later signals only latch and cannot replace that
  status, re-enter cleanup, or extend a cleanup deadline. The adapter sends
  `TERM` and, when needed, `KILL` to the registered child process group even if
  its leader already exited. It emits only
  `proton-pass age admission interrupted` and returns the fixed signal status
  after proving that the leader was reaped, the entire group is absent, the
  failed receipt is absent, and both private staging layers are removed. A
  non-`ESRCH` group probe error remains uncertain and is retried only within
  the current fixed retirement deadline. Only a later `ESRCH` proves absence;
  uncertainty at the deadline uses the failure result.
- `SIGKILL`, kernel failure, and power loss are not catchable. Cleanup does not
  run; after `SIGKILL`, a detached child process group may also continue. A
  descendant that escapes the registered process group is likewise outside
  the retirement guarantee. Keep the operation blocked, identify and terminate
  any surviving owned child, inspect only the exact mode-`0700` operation
  directory, remove that bounded directory and any ambiguous receipt, and
  rerun from fresh base/head state. Deletion is cleanup, not a secure-erasure
  guarantee for the backing storage.
- If source bytes, the trusted public fingerprint, public refs, or the pull-
  request snapshot do not match, do not retrieve the key. Reconcile the review
  or refresh the transition first.

Immediately before publishing the receipt, the adapter checks the signal latch
and blocks catchable termination only for the no-child filesystem commit. A
signal before commit entry prevents publication; a completed commit wins over a
signal deferred after entry. A failed commit restores signal delivery, removes
any caller-owned partial output when its identity still matches, and returns
the failure result. No child, provider call, or cleanup wait runs under that
mask.

## Build the offline synthetic fixture

`scripts/build-age-admission-provider-fixture` prepares the provider-free
qualification boundary. It accepts only a reviewed local Git object database,
one reviewed commit and checksum-bound manifest, one signer public key, and a
checksum-bound age 1.3.1 archive. It accepts no provider, session, credential,
private-key, GitHub, base/head, remote, or real-transition input.

The canonical `issue286-reviewed-source-manifest/v1` contains exactly these 13
sorted paths and each path's Git mode and raw-blob SHA-256:

```text
home/private_dot_local/bin/executable_proton-pass-age-admission
home/private_dot_local/bin/executable_proton-pass-ensure-ready
scripts/admit-age-envelopes
scripts/agent_equipment_public_data.py
scripts/build-age-admission-provider-fixture
scripts/create-age-admission-receipt
scripts/prepare-age-admission-recovery-preimage
scripts/privacy-scan
scripts/privacy_age_admission.py
scripts/privacy_age_envelopes.py
scripts/privacy_age_integrity_gate.py
scripts/provision-age-admission-signer
scripts/run-trusted-age-admission
```

Stage the builder itself from its raw blob at that commit. The builder disables
implicit fetch, alternates, replacement objects, hooks, filters, prompts,
protocols, and ambient Git configuration before verifying every manifest
entry. Candidate and worktree modules are not source inputs.

A standalone builder request has this exact closed shape. The values below are
synthetic examples; replace the illustrative absolute paths and digests inside
the private mode-`0600` request file.

```json
{
  "age_tooling": {
    "archive": "/private-operation/input/age-v1.3.1-platform-architecture.tar.gz",
    "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  },
  "reviewed_source": {
    "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "manifest": {
      "path": "/private-operation/input/reviewed-source-manifest.json",
      "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    },
    "repository": "/private-operation/input/reviewed-object-database"
  },
  "schema": "issue286-provider-fixture/v1",
  "signer_public_key": "/private-operation/input/disposable-signer.pub"
}
```

The request, manifest, and public-key file are canonical JSON or public-key
bytes in caller-owned, nonsymlink, single-link mode-`0600` files under
caller-owned mode-`0700` directories. The archive is a nonsymlink regular file
with the platform-specific pinned SHA-256. Create every private file
exclusively at mode `0600` before writing its first byte.
JSON inputs use UTF-8, sorted keys, two-space indentation, ASCII escaping,
standard comma/colon separators, and one final newline; reject duplicate
members, non-finite numbers, unknown members, and any other byte encoding.

Invoke only the reviewed command shape, from the private staging root that
contains the raw verified `scripts/` blob:

```zsh
python3 -I -B -S scripts/build-age-admission-provider-fixture \
  --request REQUEST.json \
  --operation-directory NEW_DIR
```

`NEW_DIR` must not exist. Success is status 0, exact standard output
`fixture-ready\n`, empty standard error, and a mode-`0600`
`NEW_DIR/fixture.json` created last. The binding fixes
`fixture.invalid/issue286-age-admission-provider`, records
`real_transition_authority=false` and `publication_permitted=false`, and binds
the synthetic repositories, signer public key, generated age identity, staged
tools, and exact `0|required\n|empty stderr` preflight. Its randomized synthetic
commits never become production evidence. The builder latches the first caught
signal, retires the full registered child process group, and removes its
uncommitted operation root before returning `128 + signal`. Later signals do
not replace the first status, re-enter cleanup, or extend either retirement
deadline. A non-`ESRCH` group probe error remains uncertain and is retried only
within the current fixed deadline; only a later `ESRCH` proves absence. A
surviving or persistently unverifiable group, operation-root identity drift,
or incomplete cleanup uses the existing failure result, retains any surviving
root as non-authoritative evidence, and creates no success marker.

Before publishing `fixture.json`, the builder checks the signal latch and
blocks catchable termination only for the no-child filesystem commit after
every child group is absent. A signal before commit entry prevents publication;
a completed commit wins over a signal deferred after entry. A failed commit
restores signal delivery and returns the failure result. No child or cleanup
wait runs under that mask. These results grant no real-transition authority.

## Qualify provider behavior and provision the signer

Issue [#136](https://github.com/nisavid/dotfiles/issues/136) remains the
discovery source for ID-based selected-field access, OS-keyring behavior,
private staging, and multiline limits. It is not admission-specific live
acceptance. Issue [#150](https://github.com/nisavid/dotfiles/issues/150) still
owns broader OpenPGP and two-host provider work; this procedure requires no
second physical host.

`scripts/provision-age-admission-signer` owns the provider-only transition. It
generates a new passphraseless Ed25519 private key inside its new private state,
stages the verified raw fixture builder, and calls that builder with only the
generated public key. It accepts no prebuilt fixture and no external private
key. It has no GitHub repository, pull-request, real base/head, merge, or
protection input or effect.

These are prepared interfaces, not authorization to run them. The owner must
separately authorize every disposable or production item, vault/share,
enrollment, provider write, revocation, deletion, and retained resource. That
live-operation boundary must also name the exact owner and primary profile
roots, keyring backend, ordinary startup maintenance and invalidation effects,
timeout behavior, and preservation or incident handling. A timeout does not
roll back a provider startup effect. The later protection exception, recovery
merge, restoration, and consumer receipts for PRs #285, #287, and #302 remain
separate owner-held effects outside this helper.

The concrete operation plan must disclose that `pass-cli agent create --vault`
resolves the supplied vault by name and upstream selects the first successfully
opened match; it cannot claim global name uniqueness. Before approval,
discovery must enumerate the provider's full returned private vault metadata
set under hard byte and time bounds, capture both streams, reject truncation
and nonempty standard error, expose only the selected projection, and have the
operator confirm its vault and share IDs. Successful selected-field readback by
the exact share ID is the final positive binding. An ambiguous or wrong
name-resolved grant is an incident and cannot produce a success marker. If the
operator does not accept that bounded risk, an exact-share-ID grant sequence is
a separate source-design decision before live qualification.

Stage the provisioning helper from its raw reviewed blob and retain the same
reviewed object database, commit, manifest, and age archive bindings used by
the fixture contract. A canonical `issue286-provisioning/v2` source-test
request has this exact closed shape:

```json
{
  "age_tooling": {
    "archive": "/private-operation/input/age-v1.3.1-platform-architecture.tar.gz",
    "sha256": "1111111111111111111111111111111111111111111111111111111111111111"
  },
  "mode": "qualification",
  "pass_cli": {
    "build_sha256": "5555555555555555555555555555555555555555555555555555555555555555",
    "version_stdout": "Proton Pass CLI 2.3.3 (abcdef0)\n"
  },
  "private_parent": "/private-operation/provisioning",
  "provider": {
    "expiration": "1h",
    "item_title": "issue286-synthetic-item",
    "recovery_agent_name": "issue286-synthetic-recovery",
    "share_id": "synthetic_share",
    "vault_name": "Synthetic Vault"
  },
  "provider_schema": {
    "command_schema": "issue286-pass-cli-2.3.3-provider-commands/v2",
    "source_commit": "51a4c9b110a0ffe6e81f4f5d3877b9e5a0c24112",
    "source_manifest_sha256": "95c0f8d872b308adb741cc21541a090ca4842cb894ece48370938955cb42ae6b"
  },
  "qualification": "source-test",
  "qualified_clean": null,
  "reviewed_source": {
    "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "manifest": {
      "path": "/private-operation/input/reviewed-source-manifest.json",
      "sha256": "6666666666666666666666666666666666666666666666666666666666666666"
    },
    "repository": "/private-operation/input/reviewed-object-database"
  },
  "schema": "issue286-provisioning/v2",
  "sessions": {
    "owner": "/private-operation/profiles/owner",
    "primary_enrollment": "/private-operation/profiles/primary",
    "primary_enrollment_name": "issue286-synthetic-primary"
  }
}
```

Private share and item IDs, vault and agent names, enrollment names, and
profile-root paths stay only in the mode-`0600` request and private state. The
v2 request retains the `sessions.owner` and `sessions.primary_enrollment` keys
for compatibility, but both values are existing Proton profile roots, not their
`.session` children. Each root and its `.session` child must already be
caller-owned, nonsymlink, mode-`0700` directories. The helper rejects either
malformed root before resolving or starting `pass-cli`.

The request carries no executable path: each child resolves `pass-cli` through
its ordinary runtime `PATH`. The helper binds the observed path, exact version
output, executable SHA-256, platform, and provider command schema for that one
operation. The observed path is not a package-location policy and need not be
equal across hosts.

The closed
`issue286-pass-cli-2.3.3-provider-commands/v2` provider schema binds pass-cli
source commit `51a4c9b110a0ffe6e81f4f5d3877b9e5a0c24112` to the maintained,
revision-wide
`docs/secret-injection/pass-cli-2.3.3-source-manifest.json`. Its SHA-256 is
`95c0f8d872b308adb741cc21541a090ca4842cb894ece48370938955cb42ae6b`.
The manifest covers all 406 files at tree
`f932a4aee404d1b45c522a8a6d39d33b7a9e50a3` and records each path, Git
mode, Git object type and ID, byte count, and raw-byte SHA-256. The recovered
six-command `pass-cli-reconciliation-source-manifest.json`, whose SHA-256 is
`1bab100ede30e745b674a5f961c1a1d7347875454685876da5e923248a330bcb`,
remains valid historical v1 schema evidence. It is not missing, and it is not
the v2 provider-source binding.

All trace paths below are relative to the
[bound public source tree](https://github.com/ProtonPass/pass-cli/tree/51a4c9b110a0ffe6e81f4f5d3877b9e5a0c24112).
The map is limited to claims this procedure consumes:

| Claim | Required source trace | Bound source fact |
| --- | --- | --- |
| Applicable command routing | `pass-cli/src/main.rs`; `pass-cli/src/commands/item/mod.rs`; `pass-cli/src/commands/agent/mod.rs`; `pass-cli/src/commands/personal_access_token/mod.rs` | The top-level parser routes `item`, `agent`, `info`, `logout`, and `personal-access-token` (alias `pat`) into these handlers. The PAT delete form requires an ID through `--personal-access-token-id` or its `--pat-id` alias. |
| Create acknowledgment | `pass-cli/src/commands/item/create/custom.rs`; `pass/src/item/create/custom.rs`; `pass/src/item/create/common.rs`; `pass-cli/src/commands/agent/create.rs`; `pass/src/personal_access_token/create.rs` | Custom-item creation prints the returned item ID after the create response. Agent creation prints token and instruction JSON only after PAT creation and Viewer grants return; it does not print the returned PAT ID. |
| Positive-only listing and skipped records | `pass-cli/src/commands/item/list.rs`; `pass/src/item/list.rs`; `pass/src/item/open.rs`; `pass-cli/src/commands/agent/list.rs`; `pass/src/personal_access_token/list.rs` | Item listing emits successfully opened item summaries and can skip records that fail state, key, content, or payload opening. PAT listing skips records it cannot open, and agent listing filters the remaining records to the agent flag. A returned exact match is positive evidence; zero matches do not prove absence or completeness. |
| Exact-ID PAT deletion acknowledgment | `pass-cli/src/main.rs`; `pass-cli/src/commands/personal_access_token/mod.rs`; `pass-cli/src/commands/personal_access_token/delete.rs`; `pass/src/personal_access_token/delete.rs` | `pass-cli pat delete --pat-id <retained_pat_id>` validates and passes that ID to the client. The client sends DELETE for that ID and applies the response success guard before the command prints `Personal access token deleted successfully`. No name lookup occurs. |
| Exact-ID item deletion acknowledgment | `pass-cli/src/commands/item/mod.rs`; `pass-cli/src/commands/item/delete.rs`; `pass/src/item/delete.rs` | The command passes the supplied share and item IDs to the client and prints `Item <item-id> deleted successfully` only after the delete response succeeds and returns. |
| Local logout and keyring cleanup | `pass-cli/src/main.rs`; `pass-cli/src/commands/logout.rs`; `pass-cli/src/features/keyring.rs`; `pass/src/logout.rs` | `logout --force` takes the pre-session force route, attempts cleanup of all key providers, removes local data, and then prints its success transcript. The ordinary logout route awaits remote session logout and separately attempts session-scoped key removal. |
| Profile-root and startup behavior | `pass-cli/src/utils.rs`; `pass-cli/src/features/mod.rs`; `pass-cli/src/features/keyring.rs`; `pass-cli/src/main.rs`; `pass-cli/src/commands/info.rs`; `pass-auth/src/store.rs` | `PROTON_PASS_SESSION_DIR` is a profile root; pass-cli appends `.session`. Provider startup may maintain or invalidate profile, keyring, database, and authentication state, and may process core events, telemetry, or refreshed authentication before the requested command completes. |
| Session-info and audit schemas | `pass-cli/src/commands/info.rs`; `pass-cli/src/commands/agent/monitor.rs`; `pass/src/monitor.rs` | JSON info distinguishes user and agent/PAT sessions through its closed optional fields. Agent monitor serializes record, vault, object, action, payload, and time fields after resolving the named agent to a PAT ID. |

The v2 cleanup target is the exact retained PAT ID. The agent name remains a
diagnostic handle. Agent-create acknowledgment establishes that the remote PAT
exists but does not establish its ID. Before arming deletion, one listing must
return exactly one same-name record with a syntactically valid PAT ID and the
expected expiration interval. If the listing returns zero or multiple
same-name records, durably retain the name, token artifact, every returned
candidate PAT ID and expiration, item handle, and private state directory. Keep
the acknowledged agent resource present without asserting an exact ID, set
remote cleanup incomplete, make no delete or other provider call, skip local
cleanup, and return status 21 with the cleanup-incomplete diagnostic.

Deletion uses only
`pass-cli pat delete --pat-id <retained_pat_id>`. Acknowledgment requires
verified normal retirement, status 0, exact standard output
`Personal access token deleted successfully\n`, and empty standard error. Any
nonzero status, signal, timeout, malformed output, unverified retirement, or
other ambiguous result retains the PAT ID, pending request, captures, and
other handles; classifies the resource as `unknown` or `removing` under the
existing transition contract; returns status 21; and permits no second
mutation on resume.

These source-order facts establish parser and control-flow behavior for the
exact transcripts. The complete source manifest does not establish that the
observed executable was built from those bytes or that a live provider durably
applied a request. Executable binding and separately owner-authorized
live-disposable-provider qualification remain required.

The two exact commands are:

```zsh
python3 -I -B -S scripts/provision-age-admission-signer start \
  --request REQUEST.json \
  --state-directory NEW_DIR

python3 -I -B -S scripts/provision-age-admission-signer resume \
  --state-directory STATE_DIR
```

`start` requires a new state directory whose lexical parent equals
`request.private_parent`. Its ordered positive phases are `validated`,
`fixture-ready`, `item-present`, `primary-readback-verified`, `agent-present`,
`session-existing`, `recovery-readback-verified`, and then one terminal phase.
Before every provider mutation it persists the exact pending request, target,
captures, prior resource state, and `requesting` or `removing` state with file
and directory synchronization. A spawn failure restores the prior local state;
once a child is created, an unacknowledged effect is never treated as absent.

A source-test run may use only disposable fakes and ends with a value-free
`qualified-clean.json` marker, exact output `qualified-clean\n`, and
`production_eligible=false`. It proves source behavior, not live-provider
acceptance. A separately owner-authorized run against disposable real provider
resources uses `qualification="live-disposable-provider"`. Only its
schema-valid, value-free, fully cleaned result may set
`production_eligible=true`; the label alone does not prove the provider was
live.

Terminal disposition uses these closed successors and fixed relative names:

| Producer artifact | Closed schema | Fixed relative name |
| --- | --- | --- |
| Provisioning request | `issue286-provisioning/v2` | Owner-selected mode-`0600` request path |
| Producer state | `issue286-provisioning-state/v2` | `state.json` |
| Qualified-clean marker | `issue286-qualified-clean/v2` | `qualified-clean.json` |
| Ready-for-recovery marker | `issue286-ready-for-recovery/v2` | `ready-for-recovery.json` |
| Prepared commit record | `issue286-terminal-commit/v1` | `.terminal-commit.prepared` |
| Final commit record | `issue286-terminal-commit/v1` | `terminal-commit.json` |

Before creating either marker, the producer computes the canonical marker and
commit-record bytes in memory. It durably adds `terminal_plan` to
`state.json`. That object has exactly `bindings`, `commit_record`,
`marker`, and `outcome`. `commit_record` has exactly
`final_name="terminal-commit.json"` and `sha256`. `marker` has exactly
`relative_path` and `sha256`. The plan's `bindings`, `marker`, and
`outcome` equal the corresponding commit-record values. The qualified-clean
commit record has this exact closed shape:

```json
{
  "bindings": {
    "pass_cli": {
      "build_sha256": "5555555555555555555555555555555555555555555555555555555555555555",
      "version_stdout": "Proton Pass CLI 2.3.3 (abcdef0)\n"
    },
    "platform": "linux",
    "provider_schema": {
      "command_schema": "issue286-pass-cli-2.3.3-provider-commands/v2",
      "source_commit": "51a4c9b110a0ffe6e81f4f5d3877b9e5a0c24112",
      "source_manifest_sha256": "95c0f8d872b308adb741cc21541a090ca4842cb894ece48370938955cb42ae6b"
    },
    "reviewed_source": {
      "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "manifest_sha256": "6666666666666666666666666666666666666666666666666666666666666666"
    }
  },
  "marker": {
    "relative_path": "qualified-clean.json",
    "sha256": "7777777777777777777777777777777777777777777777777777777777777777"
  },
  "outcome": "qualified-clean",
  "schema": "issue286-terminal-commit/v1"
}
```

The ready-for-recovery form changes only `marker.relative_path` to
`ready-for-recovery.json` and `outcome` to `ready-for-recovery`; its
marker digest and bindings come from that production operation. Canonical JSON
uses ASCII with escaped non-ASCII characters, two-space indentation,
lexicographically sorted keys, and one final newline. The marker SHA-256 is
over the exact canonical marker bytes. The commit-record SHA-256 in
`terminal_plan` is over the exact canonical commit-record bytes. The record
does not contain its own digest, the producer-state digest, or the prepared or
final filename. The production request binds the complete producer-state bytes
separately, so no digest relation is circular.

Production changes the same request only as follows:

```json
{
  "mode": "production",
  "qualification": null,
  "qualified_clean": {
    "commit_record": {
      "path": "/private-operation/evidence/terminal-commit.json",
      "sha256": "8888888888888888888888888888888888888888888888888888888888888888"
    },
    "marker": {
      "path": "/private-operation/evidence/qualified-clean.json",
      "sha256": "7777777777777777777777777777777777777777777777777777777777777777"
    },
    "producer_state": {
      "path": "/private-operation/evidence/state.json",
      "sha256": "9999999999999999999999999999999999999999999999999999999999999999"
    }
  }
}
```

Those three values replace their qualification counterparts; every other
required member remains. Before starting a provider child, production
canonicalizes and validates all three bound files. They must be owner-private
regular files in one operation directory. The producer state must carry the
qualified-clean outcome and prepared terminal plan; the marker and final
commit-record names and digests must match that plan; the commit record must
have the exact closed shape above; and its bindings must match the marker,
producer state, and current request. Missing, prepared-only, noncanonical,
mismatched, cross-operation, or non-committed combinations are rejected.
Production also requires prior live-disposable evidence whose reviewed source,
`pass-cli` version/build, platform, provider schema, cleanup checks, and
remote-resource disposition match. It then creates a fresh internal synthetic
fixture, whose randomized commits may differ from the qualification fixture.
No synthetic commit is a production binding. A successful production run
removes signer/template/token/receipt and fixture bytes, retains only bounded
private lifecycle handles, commits `ready-for-recovery.json`, emits exact
`ready-for-recovery\n`, and still grants no GitHub mutation authority.

The helper gives signer private bytes only to mode-`0600` signer/template files
and provider storage; they never enter argv, any environment, state JSON,
terminal evidence, standard output, or standard error. The agent token remains
in its private file and enters only the single `pass-cli login` child
environment with the assignment prefix removed. Other child environments
remove the token and reason first. Only selected-field readback/probe children
receive `PROTON_PASS_AGENT_REASON=age-admission signing-key retrieval`.

Provider-required IDs and names may occur in the exact private child argv and
state. Linux forces the D-Bus keyring; Darwin removes that override. Owner and
primary inputs are existing Proton profile roots; pass-cli appends `.session` to
each root. The recovery enrollment uses its task-created isolated profile root.
All use the OS keyring, update checks disabled, and the verified staged age
directory. Every provider observation may maintain or invalidate profile,
keyring, database, and authentication state, process core events and telemetry,
or persist refreshed authentication. Independent authorization therefore
requires an approved effect-bearing existing-enrollment observation, exact
recovery readback, one exact audit event, revocation, a direct post-revocation
selected-field failure without readiness, and a still-successful primary
readback. A separate directory alone is not proof; another authorized
enrollment may be on the same host.

The terminal results are closed and byte-exact:

| Result | Status and terminal bytes | Meaning |
| --- | --- | --- |
| Qualified clean | 0; `qualified-clean\n`; empty stderr | Disposable item and exact retained recovery PAT removed, revoked probe failed, primary readback still passed, local evidence cleaned, and every child group absent |
| Ready for recovery | 0; `ready-for-recovery\n`; empty stderr | Production resources verified, retained only by private handles, and every child group absent; separate recovery authorization still required |
| Failed or rolled back | 1; empty stdout; `age-admission signer provisioning failed\n` | No success evidence; provider failure, rollback, local finalization, or durable classification failed |
| Reconciliation required | 20; empty stdout; `age-admission signer provisioning requires reconciliation\n` | A create or login effect or its process-group retirement is unknown; stop as an incident |
| Cleanup incomplete | 21; empty stdout; `age-admission signer provisioning cleanup incomplete\n` | A delete or logout effect, local cleanup, or local/read-only process-group retirement is unknown; stop as an incident |
| Interrupted | `128 + signal`; empty stdout; `age-admission signer provisioning interrupted\n` | Every child group is absent and the provider state and retained evidence are durable |

Qualified clean is limited to task-created disposable provider resources, the
isolated recovery enrollment, and task-local sensitive artifacts. It does not
claim that preexisting owner or primary profiles were unchanged. An unverified
or damaged existing profile is an incident and cannot produce qualification
success. Ordinary startup maintenance already named in the approved
live-operation boundary is not an unknown item, agent, or login effect.

The first `HUP`, `INT`, or `TERM` fixes the signal status. Later signals only
latch: they cannot replace that status, re-enter finalization, extend either
retirement deadline, or authorize another provider effect. A non-`ESRCH`
group probe error remains uncertain and is retried only within the current
fixed deadline; only a later `ESRCH` proves absence. Every child leader must be
reaped and its process group proved absent before interruption or success is
reported.

A signal latched after durable mutation arming but before process creation
restores the prior resource state without a provider call and retains the local
evidence. After process creation, only accepted source-ordered item-create or
agent-create output may settle that resource as present; every other ambiguous
provider mutation remains `unknown` with its pending request, captures,
handles, and artifacts retained. Interruption adds no retry, read, logout,
revocation, deletion, or cleanup provider call.

Only normal retirement with status 0, bounded command-specific stdout, and
empty stderr acknowledges a provider request. The two pinned create commands
may also be settled by a complete source-ordered schema-valid stdout capture
with empty stderr after lost final status; a known nonzero status never settles.
Otherwise the resource becomes `unknown`. A metadata listing proves only a
positive returned record. Zero matches never prove absence, deletion,
ownership, or completeness.

`resume` converts durable `requesting` or `removing` state to `unknown` before
interpretation and performs at most one appropriate item, agent, or session
observation. It never polls, retries the ambiguous business mutation, logs in
or out, repairs readiness, deletes evidence, or continues to the next phase.
The observation still has the provider startup effects covered by the approved
live-operation boundary. Preserve the state directory and all candidate or
known handles for a separately owner-authorized incident disposition; this
helper deliberately exposes no incident-mutation interface.

Qualification cleanup is ordered: acknowledged exact retained-PAT-ID deletion,
direct revoked-session probe failure without readiness, successful primary
readback and receipt verification, acknowledged exact-ID item deletion,
acknowledged local logout, then bounded local cleanup and terminal disposition.
Do not advance past an unknown state.

For either successful outcome, the producer first checks the signal latch and
blocks catchable termination for the no-child filesystem commit. While signals
remain blocked, it durably writes the prepared state plan, writes and fsyncs the
marker and its directory, writes the canonical commit record exclusively as
`.terminal-commit.prepared`, fsyncs that file, and syncs the directory while
the record is still non-authoritative. It then performs exactly one atomic
rename from `.terminal-commit.prepared` to `terminal-commit.json`. That
rename is the publication commit point. The final name must be absent before
entry. No cleanup, state write, directory sync, or other fallible filesystem
work occurs after a successful rename; signals remain blocked through the
fixed terminal bytes and process exit. A later terminal-output failure does not
revoke or relabel the committed disposition.

Any failure before the rename leaves no final commit record. The producer
restores signal delivery, reports failure, and, when state can still be
durably updated, records `local-cleanup-incomplete`. A complete marker or
prepared record that survives failed cleanup remains non-authoritative
diagnostic evidence. Production rejects it because the final commit record is
absent or does not match the bound prepared plan. A signal before commit entry
prevents publication; a signal deferred after entry cannot replace a completed
commit. No spawn, provider call, or cleanup wait occurs under the mask. The
existing SIGKILL and host-loss limits remain: recovery trusts a final record
only when all bound files are present and validate, and absence fails closed.

Once production succeeds, keep its item and authorized enrollments until a
separately authorized replacement is accepted; never update the stored signer
in place.

## Recover trust when the current private signer is lost

The recovery pull request is the reviewed issue #286 integration plus the
single replacement of `.github/age-admission/allowed_signers`. It contains no
unrelated work. The allowed-signers file must contain exactly one record with
principal `repository-owner`, namespace
`nisavid/dotfiles/age-admission/v1`, key type `ssh-ed25519`, and the public half
whose fingerprint is `NEW_SIGNER_FINGERPRINT`.

Before requesting an exception:

1. Refresh `main` and the recovery pull request. Record the exact base and head,
   public pull ref, reviewed changed-path allowlist, tree/object IDs, source
   digests, new signer fingerprint, and all test/review results.
2. Verify locally that the new private key signs a disposable payload in the
   existing namespace and that the candidate allowed-signers file accepts it
   for `repository-owner`. Keep the private path out of logs and remove the
   payload/signature fixture afterward.
3. Require every unrelated hosted check to pass at the recovery head, at least
   one current approving review, resolved conversations, and a linear merge.
   The trusted age check is expected to reject the candidate because the base
   still trusts only the unavailable signer.
4. Verify that the activation sentinel and existing admission paths are already
   present on live `main`. That proves the one-time bootstrap path is
   inapplicable.

### Revalidate the administrative preimage

Prepare the recovery input with
`scripts/prepare-age-admission-recovery-preimage`. The helper is GitHub
read-only: it uses explicit REST `GET` requests plus one source-owned GraphQL
query over `POST` to paginate review-thread resolution. It cannot accept a
caller query, send a GraphQL mutation, call a REST mutation, merge, enable
auto-merge, or change protection.

Stage the helper from its raw blob at the reviewed source commit in the
verified source manifest. Do not invoke the candidate or worktree pathname,
and do not fetch implicitly. Record the staged blob's SHA-256 as
`RECOVERY_PREIMAGE_COLLECTOR_SHA256`; the entry gate checks both that digest and
the digest embedded in `ready.json`.

The frozen planning input observed these classic `main` protections:

| Setting | Observed value |
| --- | --- |
| Required checks | `check conventional commit compliance` (`15368`), `CodeRabbit` (`347564`), `Greptile Review` (`867647`), `zsh deployment portability` (`15368`), and `Verify trusted base against candidate data` (`15368`) |
| Strict checks | enabled |
| Pull-request review | one approval; stale reviews dismissed |
| Administrator enforcement | enabled |
| Linear history | required |
| Conversation resolution | required |
| Force pushes and deletions | disabled |
| Required signatures, branch lock, and fork syncing | disabled |
| Effective rules and rulesets | none observed |

This snapshot is only a planning precondition. Build the canonical request in
a caller-owned mode-`0700` private parent outside both checkouts. The request
contains only public repository evidence, but its mode and path rules are the
same as the bounded recovery evidence. `RECOVERY_REVIEWED_SOURCE` is the
reviewed source commit that must occur in the pull request's complete commit
list; it is not a candidate-supplied authority.

```zsh
set -euo pipefail
umask 077

file_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}
file_uid() {
  stat -c '%u' "$1" 2>/dev/null || stat -f '%u' "$1"
}
file_nlink() {
  stat -c '%h' "$1" 2>/dev/null || stat -f '%l' "$1"
}
file_sha256() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk 'NR == 1 { print $1 }'
  else
    sha256sum "$1" | awk 'NR == 1 { print $1 }'
  fi
}

: "${RECOVERY_PR_NUMBER:?set the reviewed recovery pull request number}"
: "${RECOVERY_BASE:?set the recovery pull request's current base commit}"
: "${RECOVERY_HEAD:?set the reviewed recovery pull request head commit}"
: "${RECOVERY_REVIEWED_SOURCE:?set the reviewed source commit}"
: "${RECOVERY_PREIMAGE_PRIVATE_PARENT:?set an external mode-0700 directory}"
: "${RECOVERY_PREIMAGE_COLLECTOR:?set the staged reviewed raw helper path}"
: "${RECOVERY_PREIMAGE_COLLECTOR_SHA256:?set its reviewed SHA-256}"
REPOSITORY=nisavid/dotfiles
test "$REPOSITORY" = nisavid/dotfiles
test ! -L "$RECOVERY_PREIMAGE_PRIVATE_PARENT"
RECOVERY_PREIMAGE_PRIVATE_PARENT=$(
  cd -P -- "$RECOVERY_PREIMAGE_PRIVATE_PARENT" && pwd -P
)
test -d "$RECOVERY_PREIMAGE_PRIVATE_PARENT"
test "$(file_mode "$RECOVERY_PREIMAGE_PRIVATE_PARENT")" = 700
test "$(file_uid "$RECOVERY_PREIMAGE_PRIVATE_PARENT")" = "$EUID"

collector_parent=$(
  cd -P -- "${RECOVERY_PREIMAGE_COLLECTOR:h}" && pwd -P
)
RECOVERY_PREIMAGE_COLLECTOR=$collector_parent/${RECOVERY_PREIMAGE_COLLECTOR:t}
test "$(file_mode "$collector_parent")" = 700
test "$(file_uid "$collector_parent")" = "$EUID"
test -f "$RECOVERY_PREIMAGE_COLLECTOR"
test ! -L "$RECOVERY_PREIMAGE_COLLECTOR"
test "$(file_mode "$RECOVERY_PREIMAGE_COLLECTOR")" = 600
test "$(file_uid "$RECOVERY_PREIMAGE_COLLECTOR")" = "$EUID"
test "$(file_nlink "$RECOVERY_PREIMAGE_COLLECTOR")" = 1
test "${#RECOVERY_PREIMAGE_COLLECTOR_SHA256}" = 64
case "$RECOVERY_PREIMAGE_COLLECTOR_SHA256" in
  *[!0-9a-f]*) print -u2 -- 'invalid reviewed collector SHA-256'; exit 1 ;;
esac
test "$(file_sha256 "$RECOVERY_PREIMAGE_COLLECTOR")" = \
  "$RECOVERY_PREIMAGE_COLLECTOR_SHA256"

RECOVERY_PREIMAGE_REQUEST=$RECOVERY_PREIMAGE_PRIVATE_PARENT/request.json
python3 -I -B -S - "$RECOVERY_PREIMAGE_REQUEST" "$RECOVERY_PR_NUMBER" \
  "$RECOVERY_BASE" "$RECOVERY_HEAD" "$RECOVERY_REVIEWED_SOURCE" <<'PY'
import json
import os
import stat
import sys

path, number, base, head, source = sys.argv[1:]
root = "https://api.github.com/repos/nisavid/dotfiles/branches/main/protection"
checks = [
    {"context": "check conventional commit compliance", "app_id": 15368},
    {"context": "CodeRabbit", "app_id": 347564},
    {"context": "Greptile Review", "app_id": 867647},
    {"context": "zsh deployment portability", "app_id": 15368},
    {
        "context": "Verify trusted base against candidate data",
        "app_id": 15368,
    },
]
protection = {
    "url": root,
    "required_status_checks": {
        "url": root + "/required_status_checks",
        "strict": True,
        "contexts": [record["context"] for record in checks],
        "contexts_url": root + "/required_status_checks/contexts",
        "checks": checks,
    },
    "required_pull_request_reviews": {
        "url": root + "/required_pull_request_reviews",
        "dismiss_stale_reviews": True,
        "require_code_owner_reviews": False,
        "require_last_push_approval": False,
        "required_approving_review_count": 1,
    },
    "required_signatures": {
        "url": root + "/required_signatures",
        "enabled": False,
    },
    "enforce_admins": {"url": root + "/enforce_admins", "enabled": True},
    "required_linear_history": {"enabled": True},
    "allow_force_pushes": {"enabled": False},
    "allow_deletions": {"enabled": False},
    "block_creations": {"enabled": False},
    "required_conversation_resolution": {"enabled": True},
    "lock_branch": {"enabled": False},
    "allow_fork_syncing": {"enabled": False},
}
request = {
    "schema": "issue286-recovery-preimage-request/v1",
    "repository": "nisavid/dotfiles",
    "branch": "main",
    "pull_request_number": int(number),
    "base_commit": base,
    "head_commit": head,
    "reviewed_source_commit": source,
    "required_checks": checks,
    "expected_protection": protection,
    "expected_effective_rules": [],
    "expected_rulesets": [],
}
data = (
    json.dumps(request, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    + "\n"
).encode("ascii")
fd = os.open(
    path,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
    0o600,
)
try:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
    ):
        raise SystemExit("request was not created as mode 0600")
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise SystemExit("request write failed")
        view = view[written:]
    os.fsync(fd)
finally:
    os.close(fd)
PY
test -f "$RECOVERY_PREIMAGE_REQUEST"
test ! -L "$RECOVERY_PREIMAGE_REQUEST"
test "$(file_mode "$RECOVERY_PREIMAGE_REQUEST")" = 600
test "$(file_uid "$RECOVERY_PREIMAGE_REQUEST")" = "$EUID"
test "$(file_nlink "$RECOVERY_PREIMAGE_REQUEST")" = 1

RECOVERY_STATE_DIRECTORY=$RECOVERY_PREIMAGE_PRIVATE_PARENT/initial
preimage_stdout=$RECOVERY_PREIMAGE_PRIVATE_PARENT/initial.stdout
preimage_stderr=$RECOVERY_PREIMAGE_PRIVATE_PARENT/initial.stderr
test ! -e "$RECOVERY_STATE_DIRECTORY"
test ! -L "$RECOVERY_STATE_DIRECTORY"
test ! -e "$preimage_stdout"
test ! -L "$preimage_stdout"
test ! -e "$preimage_stderr"
test ! -L "$preimage_stderr"
test "$(file_sha256 "$RECOVERY_PREIMAGE_COLLECTOR")" = \
  "$RECOVERY_PREIMAGE_COLLECTOR_SHA256"
(
  set -C
  python3 -I -B -S "$RECOVERY_PREIMAGE_COLLECTOR" \
    --request "$RECOVERY_PREIMAGE_REQUEST" \
    --state-directory "$RECOVERY_STATE_DIRECTORY" \
    >"$preimage_stdout" 2>"$preimage_stderr"
)
test -f "$preimage_stdout"
test ! -L "$preimage_stdout"
test "$(file_mode "$preimage_stdout")" = 600
test "$(file_uid "$preimage_stdout")" = "$EUID"
test "$(file_nlink "$preimage_stdout")" = 1
test -f "$preimage_stderr"
test ! -L "$preimage_stderr"
test "$(file_mode "$preimage_stderr")" = 600
test "$(file_uid "$preimage_stderr")" = "$EUID"
test "$(file_nlink "$preimage_stderr")" = 1
test ! -s "$preimage_stderr"
printf 'recovery preimage ready\n' | cmp -s - "$preimage_stdout"
test -d "$RECOVERY_STATE_DIRECTORY"
test ! -L "$RECOVERY_STATE_DIRECTORY"
test "$(file_mode "$RECOVERY_STATE_DIRECTORY")" = 700
test "$(file_uid "$RECOVERY_STATE_DIRECTORY")" = "$EUID"
test -f "$RECOVERY_STATE_DIRECTORY/ready.json"
test ! -L "$RECOVERY_STATE_DIRECTORY/ready.json"
test "$(file_mode "$RECOVERY_STATE_DIRECTORY/ready.json")" = 600
test "$(file_uid "$RECOVERY_STATE_DIRECTORY/ready.json")" = "$EUID"
test "$(file_nlink "$RECOVERY_STATE_DIRECTORY/ready.json")" = 1
RECOVERY_PREIMAGE_READY_SHA256=$(file_sha256 \
  "$RECOVERY_STATE_DIRECTORY/ready.json")
```

The launcher invokes the only supported collector command with a new
state-directory path. The helper resolves `gh` through ordinary runtime
`PATH`, bounds every capture and page, records status and standard error for
each request, performs two complete observations, and writes `ready.json`
last. Each canonical payload artifact has one shared producer-and-consumer
supported-input limit of 4 MiB (4,194,304 bytes). The collector rejects a
larger combined payload before creating its artifact or publishing readiness;
the entry gate below rejects an artifact above the same limit. Capture and
aggregate capture limits remain separate.

The expected failure of `Verify trusted base against candidate data` is the
sole prepared exception; an old-key receipt is neither required nor valid for
this recovery candidate. Its check-run read explicitly requests GitHub's
API-defined `filter=latest`. For each app-pinned required context, it retains
the complete nonempty set and accepts repeated runs only when every member is
complete for the exact head with the required conclusion. It never selects a
newest ID or infers workflow lineage. Mixed or pending results, a required
context from another app, duplicate IDs, incomplete pagination, and any
unrelated non-success all fail closed.

Record the request, helper, and ready-file digests in the reviewed operational
handoff. The collector latches the first `HUP`, `INT`, or `TERM`; later signals
cannot replace its status, re-enter finalization, or extend either retirement
deadline. It reports interruption only after durably recording that state,
reaping every child leader, proving every registered process group absent, and
withholding `ready.json`. A leader that exits while a descendant remains forces
retirement and makes a normal collection fail. An uncertain group probe or a
group that remains present records `unverified-retirement`, exits through the
failure route, retains the bounded state as diagnostic evidence, and cannot
publish readiness.

Malformed, noisy, incomplete, stale, or policy-drifted evidence likewise leaves
no ready file and grants no mutation authority. Start each later collection in
a new path. Immediately before the no-child `ready.json` commit, the collector
checks the signal latch; a signal before entry prevents publication, a
completed commit wins over a signal deferred after entry, and a failed commit
restores signal delivery before finalization. The entry gate below validates
every recorded artifact and then repeats all reads immediately before it can
arm restoration.

The minimal named exception request is:

> For issue #286 recovery PR `RECOVERY_PR_NUMBER` at exact head
> `RECOVERY_HEAD`, temporarily remove only the app-pinned required check
> `Verify trusted base against candidate data` from `main`, permit one squash
> merge after all unrelated protections pass, then restore and verify the exact
> required-check preimage before releasing the merge freeze.

GitHub applies this rule change to the branch, not only to the named pull
request. Before the owner approves it, pause auto-merge and merge queues, freeze
all other `main` merges, identify the sole operator, and verify no bot or person
will merge concurrently. Re-read live `main`, the protection digest, recovery
PR base/head, public pull ref, reviews, conversations, and unrelated checks
after the freeze. Quiescence is a gate, not an assumption.

Only the required-status-check subresource changes. Administrator enforcement,
the current approving review and stale-review rule, conversation resolution,
linear history, and the force-push and deletion bans remain enforced by GitHub
throughout the exception.

### Apply one exception, merge, and restore

These mutation commands are proposed and unrun. They require the explicit
owner authorization above.

Run the exception, one merge attempt, and restoration in one shell. The shell
arms restoration before the exception request because a failed request can
still have changed the server. One re-entrant-safe EXIT finalizer owns
restoration after any later `set -e` failure, failed comparison, or catchable
interruption. The first HUP, INT, or TERM fixes the eventual signal status;
later signals latch without aborting or re-entering restoration. A nonzero
exception PATCH never permits the merge, even if a subsequent read shows the
requested exception. A nonzero merge command is adjudicated only after
restoration by fresh pull-request and `main` reads; it is never retried.

```zsh
set -euo pipefail
: "${REPOSITORY:?set the repository}"
: "${RECOVERY_PR_NUMBER:?set the reviewed recovery pull request number}"
: "${RECOVERY_BASE:?set the recovery pull request base commit}"
: "${RECOVERY_HEAD:?set the reviewed recovery pull request head commit}"
: "${RECOVERY_STATE_DIRECTORY:?set the private recovery-state directory}"
: "${RECOVERY_PREIMAGE_REQUEST:?set the canonical preimage request path}"
: "${RECOVERY_PREIMAGE_READY_SHA256:?set the reviewed ready-file SHA-256}"
: "${RECOVERY_PREIMAGE_COLLECTOR:?set the staged reviewed raw helper path}"
: "${RECOVERY_PREIMAGE_COLLECTOR_SHA256:?set its reviewed SHA-256}"
: "${RECOVERY_FRESH_STATE_DIRECTORY:?set a new sibling state-directory path}"
: "${RECOVERY_REVIEWED_SOURCE:?set the reviewed source commit}"

test "$REPOSITORY" = nisavid/dotfiles
test "$RECOVERY_FRESH_STATE_DIRECTORY" != "$RECOVERY_STATE_DIRECTORY"
umask 077

validate_recovery_ready() {
  python3 -I -B -S - "$1" "$RECOVERY_PREIMAGE_REQUEST" \
    "$RECOVERY_PREIMAGE_COLLECTOR" "$RECOVERY_PREIMAGE_COLLECTOR_SHA256" \
    "$2" "$REPOSITORY" "$RECOVERY_PR_NUMBER" "$RECOVERY_BASE" \
    "$RECOVERY_HEAD" "$RECOVERY_REVIEWED_SOURCE" <<'PY'
import copy
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

state = Path(sys.argv[1])
request_path = Path(sys.argv[2])
collector_path = Path(sys.argv[3])
collector_sha, ready_sha = sys.argv[4:6]
repository, pull_text, base, head, source = sys.argv[6:11]
uid = os.getuid()
sha_pattern = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
commit_pattern = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
artifact_pattern = re.compile(
    r"(?:captures|payloads)/[A-Za-z0-9._-]{1,160}\Z", re.ASCII
)
exception_context = "Verify trusted base against candidate data"
expected_limits = {
    "capture_stderr_bytes": 65536,
    "capture_stdout_bytes": 4194304,
    "capture_timeout_seconds": 30,
    "capture_total_bytes": 67108864,
    "max_artifacts": 256,
    "max_pages": 5,
    "page_size": 100,
    "ready_bytes": 1048576,
    "request_bytes": 1048576,
    "terminate_grace_seconds": 2,
    "total_timeout_seconds": 180,
}


def stop(message):
    raise ValueError(message)


def canonical(value):
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")


def no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            stop("duplicate JSON member")
        value[key] = item
    return value


def load_canonical(data):
    value = json.loads(
        data.decode("utf-8", "strict"),
        object_pairs_hook=no_duplicates,
        parse_constant=lambda _value: stop("non-finite JSON number"),
    )
    if canonical(value) != data:
        stop("noncanonical JSON")
    return value


def require_path(path):
    text = os.fspath(path)
    if not text.startswith("/") or os.path.normpath(text) != text:
        stop("path is not absolute and normalized")
    current = Path("/")
    for part in path.parts[1:]:
        current /= part
        if stat.S_ISLNK(os.lstat(current).st_mode):
            stop("symlink traversal")


def require_directory(path, mode=0o700):
    require_path(path)
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != mode
        or info.st_uid != uid
    ):
        stop("private directory metadata")


def read_file(path, limit, *, allow_empty=False):
    require_path(path)
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != uid
            or info.st_nlink != 1
            or info.st_size > limit
            or (not allow_empty and info.st_size == 0)
        ):
            stop("private file metadata")
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > limit:
            stop("private file size")
        return data
    finally:
        os.close(descriptor)


def digest(data):
    return hashlib.sha256(data).hexdigest()


try:
    for value in (collector_sha, ready_sha):
        if sha_pattern.fullmatch(value) is None:
            stop("invalid expected digest")
    if repository != "nisavid/dotfiles" or not pull_text.isascii():
        stop("invalid recovery binding")
    pull_number = int(pull_text)
    if pull_number <= 0 or str(pull_number) != pull_text:
        stop("invalid pull number")
    if any(commit_pattern.fullmatch(value) is None for value in (base, head, source)):
        stop("invalid commit binding")

    require_directory(state.parent)
    require_directory(state)
    require_directory(request_path.parent)
    require_directory(collector_path.parent)
    require_directory(state / "captures")
    require_directory(state / "payloads")
    if set(os.listdir(state)) != {"captures", "payloads", "ready.json"}:
        stop("unexpected state entry")

    collector_data = read_file(collector_path, 1048576)
    if digest(collector_data) != collector_sha:
        stop("collector digest mismatch")
    request_data = read_file(request_path, 1048576)
    request = load_canonical(request_data)
    request_keys = {
        "base_commit", "branch", "expected_effective_rules", "expected_protection",
        "expected_rulesets", "head_commit", "pull_request_number", "repository",
        "required_checks", "reviewed_source_commit", "schema",
    }
    if not isinstance(request, dict) or set(request) != request_keys:
        stop("request schema")
    if (
        request["schema"] != "issue286-recovery-preimage-request/v1"
        or request["repository"] != repository
        or request["branch"] != "main"
        or request["pull_request_number"] != pull_number
        or request["base_commit"] != base
        or request["head_commit"] != head
        or request["reviewed_source_commit"] != source
        or request["expected_effective_rules"] != []
        or request["expected_rulesets"] != []
    ):
        stop("request binding")
    checks = request["required_checks"]
    if not isinstance(checks, list) or len(checks) != 5:
        stop("required checks")
    contexts = set()
    for record in checks:
        if not isinstance(record, dict) or set(record) != {"context", "app_id"}:
            stop("required-check schema")
        context, app_id = record["context"], record["app_id"]
        if (
            not isinstance(context, str)
            or not context
            or context in contexts
            or not isinstance(app_id, int)
            or isinstance(app_id, bool)
            or app_id <= 0
        ):
            stop("required-check value")
        contexts.add(context)
    if sum(record["context"] == exception_context for record in checks) != 1:
        stop("recovery exception")
    sorted_checks = sorted(checks, key=lambda record: (record["context"], record["app_id"]))

    ready_data = read_file(state / "ready.json", 1048576)
    if digest(ready_data) != ready_sha:
        stop("ready digest mismatch")
    ready = load_canonical(ready_data)
    ready_keys = {
        "artifacts", "binding", "collector_sha256", "graphql_query_sha256",
        "limits", "observations_sha256", "outcome", "payloads",
        "request_sha256", "schema",
    }
    if not isinstance(ready, dict) or set(ready) != ready_keys:
        stop("ready schema")
    if (
        ready["schema"] != "issue286-recovery-preimage-ready/v1"
        or ready["outcome"] != "ready"
        or ready["collector_sha256"] != collector_sha
        or ready["graphql_query_sha256"]
        != "c1d9596eead2a652ce7f33120b48e03b7aaf533f2f5b719a88dd74196f631d54"
        or ready["request_sha256"] != digest(request_data)
        or ready["limits"] != expected_limits
    ):
        stop("ready binding")
    expected_binding = {
        "repository": repository,
        "branch": "main",
        "pull_request_number": pull_number,
        "base_commit": base,
        "head_commit": head,
        "reviewed_source_commit": source,
        "required_checks": sorted_checks,
    }
    if ready["binding"] != expected_binding:
        stop("ready request binding")

    artifacts = ready["artifacts"]
    if (
        not isinstance(artifacts, list)
        or not 1 <= len(artifacts) <= 256
        or not all(isinstance(record, dict) for record in artifacts)
    ):
        stop("artifact count")
    if [record.get("path") for record in artifacts] != sorted(
        record.get("path") for record in artifacts
    ):
        stop("artifact order")
    artifact_map = {}
    total_bytes = 0
    allowed_kinds = {
        "capture-stdout", "capture-stderr", "capture-status", "graphql-input",
        "observations", "protection-preimage", "restore-payload", "exception-payload",
    }
    for record in artifacts:
        if not isinstance(record, dict) or set(record) != {"bytes", "kind", "path", "sha256"}:
            stop("artifact schema")
        relative = record["path"]
        size = record["bytes"]
        if (
            not isinstance(relative, str)
            or artifact_pattern.fullmatch(relative) is None
            or relative in artifact_map
            or record["kind"] not in allowed_kinds
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or size > 4194304
            or not isinstance(record["sha256"], str)
            or sha_pattern.fullmatch(record["sha256"]) is None
        ):
            stop("artifact value")
        prefix = relative.split("/", 1)[0]
        if (prefix == "captures") != record["kind"].startswith(("capture-", "graphql-")):
            stop("artifact location")
        data = read_file(state / relative, 4194304, allow_empty=True)
        if len(data) != size or digest(data) != record["sha256"]:
            stop("artifact digest")
        artifact_map[relative] = record
        total_bytes += size
    if total_bytes > 67108864:
        stop("artifact total")
    actual_paths = {
        f"{directory}/{name}"
        for directory in ("captures", "payloads")
        for name in os.listdir(state / directory)
    }
    if actual_paths != set(artifact_map):
        stop("artifact completeness")

    payloads = ready["payloads"]
    payload_kinds = {
        "observations": "observations",
        "protection_preimage": "protection-preimage",
        "restore_checks": "restore-payload",
        "exception_checks": "exception-payload",
    }
    if not isinstance(payloads, dict) or set(payloads) != set(payload_kinds):
        stop("payload schema")
    payload_values = {}
    for name, kind in payload_kinds.items():
        reference = payloads[name]
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
            stop("payload reference")
        record = artifact_map.get(reference["path"])
        if record is None or record["kind"] != kind or record["sha256"] != reference["sha256"]:
            stop("payload artifact binding")
        payload_values[name] = load_canonical(read_file(state / reference["path"], 4194304))
    if ready["observations_sha256"] != payloads["observations"]["sha256"]:
        stop("observation digest")

    expected_protection = copy.deepcopy(request["expected_protection"])
    expected_protection["required_status_checks"]["contexts"].sort()
    expected_protection["required_status_checks"]["checks"].sort(
        key=lambda record: (record["context"], record["app_id"])
    )
    if payload_values["protection_preimage"] != expected_protection:
        stop("protection payload")
    if payload_values["restore_checks"] != {"strict": True, "checks": sorted_checks}:
        stop("restore payload")
    exception_checks = [
        record for record in sorted_checks if record["context"] != exception_context
    ]
    if payload_values["exception_checks"] != {"strict": True, "checks": exception_checks}:
        stop("exception payload")
except (
    AttributeError,
    IndexError,
    KeyError,
    OSError,
    TypeError,
    UnicodeError,
    ValueError,
):
    print("recovery preimage ready gate failed", file=sys.stderr)
    raise SystemExit(1)
PY
}

validate_recovery_ready "$RECOVERY_STATE_DIRECTORY" \
  "$RECOVERY_PREIMAGE_READY_SHA256"
test ! -e "$RECOVERY_FRESH_STATE_DIRECTORY"
fresh_stdout=$RECOVERY_FRESH_STATE_DIRECTORY.stdout
fresh_stderr=$RECOVERY_FRESH_STATE_DIRECTORY.stderr
(
  set -C
  python3 -I -B -S "$RECOVERY_PREIMAGE_COLLECTOR" \
    --request "$RECOVERY_PREIMAGE_REQUEST" \
    --state-directory "$RECOVERY_FRESH_STATE_DIRECTORY" \
    >"$fresh_stdout" 2>"$fresh_stderr"
)
test ! -s "$fresh_stderr"
printf 'recovery preimage ready\n' | cmp -s - "$fresh_stdout"
cmp -s "$RECOVERY_STATE_DIRECTORY/ready.json" \
  "$RECOVERY_FRESH_STATE_DIRECTORY/ready.json"
validate_recovery_ready "$RECOVERY_FRESH_STATE_DIRECTORY" \
  "$RECOVERY_PREIMAGE_READY_SHA256"

ready=$RECOVERY_STATE_DIRECTORY/ready.json
protection_preimage=$RECOVERY_STATE_DIRECTORY/$(jq -er \
  '.payloads.protection_preimage.path' "$ready")
restore_checks=$RECOVERY_STATE_DIRECTORY/$(jq -er \
  '.payloads.restore_checks.path' "$ready")
exception_checks=$RECOVERY_STATE_DIRECTORY/$(jq -er \
  '.payloads.exception_checks.path' "$ready")
test -f "$protection_preimage"
test -f "$restore_checks"
test -f "$exception_checks"

protection_endpoint="repos/$REPOSITORY/branches/main/protection"
checks_endpoint="$protection_endpoint/required_status_checks"
pull_endpoint="repos/$REPOSITORY/pulls/$RECOVERY_PR_NUMBER"
merge_endpoint="$pull_endpoint/merge"
main_ref_endpoint="repos/$REPOSITORY/git/ref/heads/main"
exception_expected=$RECOVERY_STATE_DIRECTORY/main-protection.exception.expected.json
preimage_canonical=$RECOVERY_STATE_DIRECTORY/main-protection.preimage.canonical.json
restore_state=unarmed
finalizer_state=idle
restore_attempt=0
first_signal_status=0
recovery_exit_status=0
finalizer_entry_state=idle

canonicalize_protection() {
  jq -S '
    .required_status_checks.contexts |= sort
    | .required_status_checks.checks |=
        sort_by(.context, .app_id)
  ' "$1"
}

recovery_github_api() {
  gh api --hostname github.com \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2022-11-28' \
    "$@"
}

jq --arg omitted 'Verify trusted base against candidate data' '
  .required_status_checks.contexts |= map(select(. != $omitted))
  | .required_status_checks.checks |=
      map(select(.context != $omitted))
' "$protection_preimage" >"$exception_expected"
canonicalize_protection "$protection_preimage" >"$preimage_canonical"

restore_and_verify() {
  case "$restore_state" in
    armed|failed) ;;
    *) print -u2 -- 'restoration entered from an invalid state'; return 1 ;;
  esac
  restore_state=restoring
  restore_attempt=$((restore_attempt + 1))
  local suffix=$restore_attempt
  local response=$RECOVERY_STATE_DIRECTORY/required-checks.restore.response.$suffix.json
  local observed=$RECOVERY_STATE_DIRECTORY/main-protection.restored.$suffix.json
  local observed_canonical=$RECOVERY_STATE_DIRECTORY/main-protection.restored.$suffix.canonical.json
  local patch_status=0

  if recovery_github_api --method PATCH "$checks_endpoint" \
    --input "$restore_checks" >"$response"; then
    patch_status=0
  else
    patch_status=$?
  fi

  if recovery_github_api "$protection_endpoint" >"$observed" &&
    canonicalize_protection "$observed" >"$observed_canonical" &&
    cmp -s "$preimage_canonical" "$observed_canonical"; then
    if (( patch_status != 0 )); then
      print -u2 -- 'restore PATCH was ambiguous; fresh full protection matches the preimage'
    fi
    restore_state=verified
    return 0
  fi

  restore_state=failed
  print -u2 -- 'required-check restoration is not verified'
  return 1
}

latch_recovery_signal() {
  local requested_status=$1
  if (( first_signal_status == 0 )); then
    first_signal_status=$requested_status
  fi
  if [[ $restore_state == restoring || $finalizer_state == running ]]; then
    return 0
  fi
  exit "$first_signal_status"
}

finish_recovery() {
  local incoming_status=$1
  local final_status=$incoming_status
  trap - EXIT

  if [[ $restore_state == armed || $restore_state == failed ]]; then
    if ! restore_and_verify; then
      final_status=125
    fi
  elif [[ $restore_state == restoring ]]; then
    restore_state=failed
    final_status=125
  fi

  if [[ $restore_state == failed ]]; then
    print -u2 -- 'recovery exited with the required check potentially absent'
    final_status=125
  elif (( first_signal_status != 0 )); then
    final_status=$first_signal_status
  fi
  finalizer_state=done
  exit "$final_status"
}

recovery_exit_trap() {
  recovery_exit_status=$? finalizer_entry_state=$finalizer_state \
    finalizer_state=${finalizer_state/idle/running}
  if [[ $finalizer_entry_state != idle ]]; then
    return 0
  fi
  finish_recovery "$recovery_exit_status"
}

trap recovery_exit_trap EXIT
trap 'latch_recovery_signal 129' HUP
trap 'latch_recovery_signal 130' INT
trap 'latch_recovery_signal 143' TERM

exception_response=$RECOVERY_STATE_DIRECTORY/required-checks.exception.response.json
exception_observed=$RECOVERY_STATE_DIRECTORY/main-protection.exception.json
exception_expected_canonical=$RECOVERY_STATE_DIRECTORY/main-protection.exception.expected.canonical.json
exception_observed_canonical=$RECOVERY_STATE_DIRECTORY/main-protection.exception.canonical.json

restore_state=armed
exception_patch_status=0
if recovery_github_api --method PATCH "$checks_endpoint" \
  --input "$exception_checks" >"$exception_response"; then
  exception_patch_status=0
else
  exception_patch_status=$?
fi
if (( exception_patch_status != 0 )); then
  print -u2 -- 'exception PATCH was ambiguous; refusing the merge'
  exit 1
fi

recovery_github_api "$protection_endpoint" >"$exception_observed"
canonicalize_protection "$exception_expected" \
  >"$exception_expected_canonical"
canonicalize_protection "$exception_observed" \
  >"$exception_observed_canonical"
cmp -s "$exception_expected_canonical" "$exception_observed_canonical"

pull_before=$RECOVERY_STATE_DIRECTORY/recovery-pr.before-merge.json
main_before=$RECOVERY_STATE_DIRECTORY/main-ref.before-merge.json
recovery_github_api "$pull_endpoint" >"$pull_before"
recovery_github_api "$main_ref_endpoint" >"$main_before"
jq -e --arg base "$RECOVERY_BASE" --arg head "$RECOVERY_HEAD" '
  .state == "open" and .merged == false and
  .base.ref == "main" and .base.sha == $base and .head.sha == $head
' "$pull_before" >/dev/null
test "$(jq -r .object.sha "$main_before")" = "$RECOVERY_BASE"

merge_request=$RECOVERY_STATE_DIRECTORY/recovery-merge.request.json
merge_response=$RECOVERY_STATE_DIRECTORY/recovery-merge.response.json
merge_stderr=$RECOVERY_STATE_DIRECTORY/recovery-merge.stderr
jq -n --arg sha "$RECOVERY_HEAD" '{
  sha: $sha,
  merge_method: "squash"
}' >"$merge_request"
merge_command_status=0
if recovery_github_api --method PUT "$merge_endpoint" --input "$merge_request" \
  >"$merge_response" 2>"$merge_stderr"; then
  merge_command_status=0
else
  merge_command_status=$?
fi

explicit_restore_status=0
if restore_and_verify; then
  explicit_restore_status=0
else
  explicit_restore_status=$?
fi
if (( first_signal_status != 0 )); then
  exit "$first_signal_status"
fi
if (( explicit_restore_status != 0 )); then
  print -u2 -- 'the immediate restore attempt failed; the EXIT trap will retry once'
  exit 125
fi

pull_after=$RECOVERY_STATE_DIRECTORY/recovery-pr.after-restore.json
main_after=$RECOVERY_STATE_DIRECTORY/main-ref.after-restore.json
recovery_github_api "$pull_endpoint" >"$pull_after"
recovery_github_api "$main_ref_endpoint" >"$main_after"
main_after_sha=$(jq -er .object.sha "$main_after")

if jq -e '.merged == true' "$pull_after" >/dev/null; then
  jq -e --arg head "$RECOVERY_HEAD" --arg main "$main_after_sha" '
    .head.sha == $head and .merge_commit_sha == $main
  ' "$pull_after" >/dev/null
  if (( merge_command_status == 0 )); then
    jq -e --arg main "$main_after_sha" '
      .merged == true and .sha == $main
    ' "$merge_response" >/dev/null
  fi
  print -r -- 'recovery merge observed and required checks restored'
  exit 0
fi

jq -e '.merged == false' "$pull_after" >/dev/null
test "$main_after_sha" = "$RECOVERY_BASE"
if (( merge_command_status == 0 )); then
  jq -e '.merged == false' "$merge_response" >/dev/null
  print -u2 -- 'merge API left the recovery pull request unmerged'
  exit 1
fi
print -u2 -- 'recovery pull request remains unmerged; required checks restored'
exit "$merge_command_status"
```

Canonicalize and compare the fresh full response with the saved preimage,
including all five app-pinned checks and every unrelated protection. Repeat the
effective-rule and ruleset reads. Keep the merge freeze until the comparison
passes and live `main` is shown to contain the reviewed recovery tree and the
single new allowed-signer fingerprint.

The state machine prevents its own merge attempt after an ambiguous exception
PATCH or failed exception comparison. Restoration stays armed until a fresh
full protection response exactly matches the saved preimage. The first caught
signal fixes the eventual status; signals received while restoration or the
EXIT finalizer runs only latch and cannot re-enter or abort finalization. Exit
or a signal after arming but before an explicit restore causes one EXIT restore
attempt. An explicit restore that succeeds or observes the exact preimage uses
one restore PATCH. A failed explicit restore receives one EXIT retry, for two
total; a failed EXIT-initiated attempt is not recursively retried.

These controls cannot make the GitHub operations atomic, survive `SIGKILL`,
power loss, host loss, or a sustained GitHub API or network outage, or stop
another authorized actor from merging while the required check is absent.

No supported enforceable recovery-only hold is present in the recorded policy.
During the exception window, repository protection does not technically block
other changes that satisfy the remaining requirements. The merge freeze is a
human coordination control, not repository admission enforcement. Before any
production operation, the owner must explicitly choose either to accept that
residual window for this named recovery under verified quiescence, or to defer
recovery until an enforceable hold is separately designed and authorized. No
acceptance is recorded by this prepared proposal. If restoration cannot be
verified, declare an incident and maintain the human freeze; do not claim that
GitHub has technically blocked admission, and do not create or publish an age
receipt until an authorized operator restores and verifies protection.

### Recovery failure and rollback

- Before merge, rollback is exact: restore the required-check preimage, verify
  the full protection response and live `main`, and leave the recovery PR
  unmerged. The unavailable old signer means admission remains blocked.
- If the provider item or recovery enrollment fails qualification before merge,
  do not change repository trust. Remove or revoke only the explicitly
  authorized failed provider resources and prepare a new item; do not update
  failed key material in place.
- If the exception is active but the merge has not occurred, restore first.
  If GitHub cannot confirm restoration, maintain the human merge freeze; the
  remaining repository policy may still admit another eligible change. Do not
  assume the failed merge restored policy.
- If the recovery merge occurred but protection restoration fails, the new key
  may be present while the merge boundary is degraded. Do not use that key or
  merge again until protection is restored and verified.
- If the merged public key and retained private key do not work, there is no
  implemented automatic rollback and the unavailable signer cannot authorize a
  revert. Withhold receipts and operator approval. If the required check is
  still absent, that withholding is not a technical repository block.
  Replacing the bad key requires a new, separately authorized named
  administrative recovery; bootstrap remains unavailable.

Automation may prepare snapshots, payloads, hashes, tree comparisons, tests,
and post-change reads. The owner retains authorization of the provider writes,
new isolated enrollment, temporary protection patch, exact recovery merge,
restoration, incident decisions, and any second recovery. Never let a script
infer or broaden that authority.

## Activate the consumers and close the issue

PR [#285](https://github.com/nisavid/dotfiles/pull/285),
PR [#287](https://github.com/nisavid/dotfiles/pull/287), and
PR [#302](https://github.com/nisavid/dotfiles/pull/302) consume the reviewed
procedure under their separate owning tasks. PR #285's head was
`6a9b527e87b21967dbb8f43d2c2c15af8658e772` when this procedure was prepared;
that value and any observed PR #287 or PR #302 base or head are not reusable
operating inputs. Before any later operation, each consumer must independently
load the published, reviewed issue #286 revision, record that revision plus the
refreshed adapter, trusted-wrapper, and creator digests, and refresh its own
then-current base and head. A local candidate, an earlier digest handoff, or
another consumer's transition is not an operating input.

Once the new key is trusted, protection is restored, and operational acceptance
is recorded, each owning task may, under its separate authority, create a new
receipt through the routine path, replace that PR's prior marker, and require a
fresh hosted `Verify trusted base against candidate data` run for that exact
then-current transition. Each owner retains its work. This handoff changes none
of those pull requests and transfers no branch, source, receipt, review, or
integration ownership.

[PR #253](https://github.com/nisavid/dotfiles/pull/253) is the public retired-key
control. Bind later verification to these exact public bytes:

- receipt marker SHA-256
  `c47e43df68c63b8883bb9386d986d8f991e0725631a5ea5dce9f7b1fdc0dd16e`;
- canonical payload SHA-256
  `5d4fedd9d13eba26fbf52af0a4452c666468588ac9156d1ac43fbddf6cbdf348`;
- signature SHA-256
  `177e3c135117044fdcf0b44d1f7f3412ec223f78c67b3c02c7ba99284f0f2d33`;
- base `e5c0987ce647917c4f434b43ebdfc13a579e63f6`, head
  `ae1396f7ef211892600df76dfecaf49f379f4493`, and explicit historical
  validation time `2026-09-02T20:37:30Z`; and
- the successful GitHub Actions
  [trusted-base check](https://github.com/nisavid/dotfiles/actions/runs/33679503445/job/100415257548)
  for that head.

Unmodified verifier modules from trusted revision
`d2ba32e7ab8c9d9abb815533e6b4f96dc6c242ea` validated the canonical payload at
that historical time and verified its SSH signature against the pre-recovery
allowed-signers blob. This establishes a formerly valid signed control. The
receipt expired at `2026-09-03T19:03:24Z`; current-time receipt extraction
rejects it for expiry and proves nothing about signer retirement.

After recovery, verify the already isolated canonical signature directly
against both signer blobs: it must still verify against the pre-recovery blob
and must fail against the recovered `main` blob. Do not run current-time receipt
extraction and label its expiry error as retired-key rejection. In a separately
authorized disposable protected transition, also require the hosted gate to
reject the retired receipt before publishing a new-key receipt. The recovered-
signer comparison and hosted fresh-transition check remain unexecuted and need
their existing production authorization. This control requires no copy of the
retired private key and separates signer retirement from exact-transition and
expiry checks.

Before closing issue #286, retain value-free evidence of all of these outcomes:

- the reviewed published source revision, adapter/wrapper digests, and clean
  fixture tests;
- successful admission-specific provider qualification and recovery through
  the second authorized enrollment;
- live `main` containing exactly the accepted new signer;
- the PR #253 canonical signature rejected by the recovered signer blob, while
  its historical validation against the pre-recovery blob remains reproducible,
  and the retired receipt rejected on a new transition;
- the full restored protection response matching its preimage, including the
  app-pinned trusted-base check;
- separate new-key receipts and fresh hosted successes for PRs #285, #287,
  and #302 at their independently refreshed base/head transitions; and
- absence of adapter and receipt-creator private staging plus the operational
  handoff.

The public PR #253 control settles only the historical side of that comparison.
Static inspection of the one-key allowed-signers file is not enough to claim
the pending recovered-key rejection. Keep issue #286 open until that dynamic
comparison and the authorized hosted transition complete.
