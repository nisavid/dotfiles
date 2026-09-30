# Qualify the PQ Sequoia macOS candidate

This procedure builds and exercises the reviewed `sq` 1.4.0 and `sqv` 1.5.0
candidate on a fresh GitHub-hosted `macos-15` runner. It records public,
value-free evidence; it does not install a runtime on a personal Mac or grant
production, custody, publication, or acceptance authority.

Use it when an immutable application, lock, formula, tap commit, OpenSSL,
bottle, executable, linked-library, dyld shared-cache membership, runner-image,
protocol, or procedure identity changes. The candidate remains disabled until
the complete local and live bidirectional matrix succeeds at one reviewed
revision and receives separate acceptance.

## Maintained inputs

- [`candidate.json`](../../../packaging/homebrew/pq-sequoia-macos/v1/candidate.json)
  fixes the application tags and commits, source and formula bytes, retained
  lock patches, final lock digests, release signers, OpenSSL source and signer,
  the Homebrew/core formula revision, and the Apple Silicon Sequoia bottle.
- [`interop-v1.json`](interop-v1.json) defines the four-phase exchange with
  dotfiles #148. Its review-candidate SHA-256 is
  `d11f864ed4e8a60e039ae1d6753f033620614309c917b3f409c05a65d07fbe48`.
  Its fixed [message](fixtures/v1/message.bin) is exactly 51 bytes and has SHA-256
  `6be8c2fe3154649151aacd41f35dd6a212881e627acca131fe3f0101b14f4337`.
- [`pq-sequoia-macos`](../../../scripts/pq-sequoia-macos) validates those
  inputs, parses release-signature status, compares signed Git trees with
  pre-patch archives, binds Homebrew's active OpenSSL formula, commits and
  verifies the ephemeral tap, inspects key-packet versions, controls exact-keg
  selection, records the Mach-O and runtime closures, and opens and closes the
  live exchange. Its `record-relay-observation` command validates and records
  complete paginated selection and final relay checks.
- [`pq-sequoia-macos.yml`](../../../.github/workflows/pq-sequoia-macos.yml) is
  manual-only. It has no push, pull-request, schedule, or release trigger.

The selected OpenSSL closure is Homebrew `openssl@3.5` 3.5.8, not the
preflight's OpenSSL 3.6.4 proposal. OpenSSL lists 3.5 as LTS through 2030-04-08,
and Homebrew provides a keg-only 3.5 formula with an Apple Silicon Sequoia
bottle. The workflow verifies the official detached release signature, source,
formula, and bottle bytes before use. It checks out the declared Homebrew/core
revision with API-based formula resolution disabled, requires Homebrew's own
formula resolver to return the declared formula path, and compares those live
bytes with the candidate before any package installation. The same formula
identity is observed again after the private formula builds and retained in
the runtime closure.

## Validate the checked-in surface

Run this after any edit to the procedure, protocol, formulae, or lock patches:

```sh
scripts/pq-sequoia-macos validate-static --root .
python3 -B -m unittest tests.test_pq_sequoia_macos
ruff check --no-cache scripts/pq-sequoia-macos tests/test_pq_sequoia_macos.py
actionlint .github/workflows/pq-sequoia-macos.yml
```

The command fails closed on any formula, patch, message, or manifest mismatch.
The formulae embed the same reviewed patch bytes retained beside them; the test
and command require the two copies to remain byte-identical. Inert source
fixtures also require exactly one structurally valid GnuPG `VALIDSIG` record,
exercise every declared signing-subkey identity, reject a pre-patch archive
whose normalized tree differs from its signed commit, and reject an active
formula whose path, bytes, or Homebrew/core revision differs while the
separately downloaded formula remains unchanged.

## Verify source provenance before build

For each `sq` and `sqv` tag, retain GnuPG's machine-readable status and require
exactly one `VALIDSIG` record. Its signing-key fingerprint must equal the
declared signing subkey, and its primary-key fingerprint must equal the
declared primary. Apply the same rule to the OpenSSL detached signature.
Missing, duplicate, malformed, or mismatched records stop before a source
receipt is written.

After validation, the workflow copies the exact status bytes into the public
evidence tree as `source-sq-validsig.status`,
`source-sqv-validsig.status`, and `source-openssl-validsig.status`. Each
corresponding signer receipt records the retained file's SHA-256. Downloads,
source archives, public-key imports, the GnuPG home, and unrelated diagnostics
remain outside the success artifact.

Extract each Sequoia release archive without patching it, then compare it with
the tree named by the verified tag commit. The normalization includes every
tracked regular file and symbolic link, its repo-relative path, Git mode, byte
count, and SHA-256 content digest; it ignores directories because Git does not
track empty directories. The archive wrapper directory is removed during
extraction. Any missing, extra, changed, mode-different, or unsupported entry
stops before the lock patch, upstream tests, or package build.

`source-verification.json` retains each observed primary and signing
fingerprint, signed commit and Git tree, both normalized tree digests, the
active OpenSSL formula path and digest, and the exact Homebrew/core revision.
`runtime-closure.json` embeds that receipt and a second active-formula
observation made after the candidate builds. A difference between the two
formula observations rejects runtime-closure creation.

## Prepare the #148 public opening phase

The coordinator creates `session_id` from 32 bytes returned by a
cryptographically secure random generator and never reuses it, including after
a failed attempt. The coordinator also supplies the exact reviewed Hatchery
closure SHA-256; the peer envelope does not establish that expected value.

The #148 consumer loads the exact protocol bytes, generates and inspects a
disposable certificate, and rejects anything except a version-6
ML-DSA-65+Ed25519 certify-only primary, a version-6 ML-DSA-65+Ed25519
signing-only subkey, and a version-6 ML-KEM-768+X25519 encryption-only subkey.
There must be no authentication capability or additional subkey. It similarly
inspects each detached signature and requires version 6,
ML-DSA-65+Ed25519, and the exact signing-subkey issuer fingerprint.
Certificate algorithms and capabilities come from `sq inspect`; each key
version comes from the corresponding fingerprinted `Public-Key Packet` or
`Public-Subkey Packet` emitted by `sq packet dump`. The receiver rejects a
missing, duplicated, mismatched, or non-version-6 packet observation.
Treat the text dump as packet records: every packet heading ends the active
key record, and only a public-key or public-subkey heading starts another one.
Never use `Version`, `Pk algo`, or `Fingerprint` fields from a following
signature, user ID, or other packet to complete or replace a key observation.
The maintained public-entrypoint fixture recreates the pinned `sq` 1.4.0 dump
shape with a direct self-signature, a positive certification self-signature,
and subkey-binding signatures. It also requires malformed and wrong-version
key records to fail closed. These recreated cases are new source-test evidence,
not a generated certificate, built `sq` observation, independent review, or
hosted macOS result.

`hatchery-phase-a.json` contains the disposable public certificate, its
detached signature over the fixed message, the protocol digest, reviewed
Hatchery closure digest, fresh session, fixed-message digest, and the all-zero
genesis parent. Its `control_signature` is a second detached signature made by
the same disposable signing subkey over the canonical envelope transcript.
Canonical bytes exclude `control_signature`, recursively sort object keys,
use JSON `ensure_ascii=true` with `,` and `:` separators, encode as UTF-8, and
have no terminal newline. In Python, the byte operation is:

```python
json.dumps(
    {key: value for key, value in envelope.items() if key != "control_signature"},
    ensure_ascii=True,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")
```

The envelope records all four local revocation checks as value-free results.

The Hatchery secret certificate stays in #148's isolated temporary storage
from `hatchery-open` through `hatchery-return`. If it is destroyed before the
return phase, stop: no later rebuild can stand in for that session.

Validate the opening envelope before dispatch:

```sh
scripts/pq-sequoia-macos validate-envelope \
  --phase hatchery-phase-a \
  --session-id "$session_id" \
  --expected-producer-closure-sha256 "$hatchery_closure_sha256" \
  --expected-parent-sha256 "$(printf '0%.0s' {1..64})" \
  hatchery-phase-a.json
```

The coordinator computes the exact envelope SHA-256 and base64 bytes without
rewriting them. Secret keys, secret certificates, Sequoia homes, revocation
packets, plaintext derivatives, and tampered inputs are never included.

## Dispatch the reviewed macOS revision

`workflow_dispatch` requires this workflow to exist on the default branch.
For the first run, land the reviewed implementation, bind a fresh review to the
resulting published revision, and dispatch that same revision. Observe the
selected ref immediately before dispatch; the job compares
`GITHUB_WORKFLOW_SHA`, the checked-out commit, and `candidate_commit` and fails
if they differ.

Both workflow modes accept only `GITHUB_RUN_ATTEMPT=1`; each job checks this
before checkout or exchange input use. Do not rerun a failed qualification or
response job. End that exchange, then use
a fresh session identifier and new workflow runs.

```sh
gh workflow run pq-sequoia-macos.yml \
  --ref "$reviewed_ref" \
  -f mode=qualify \
  -f candidate_commit="$reviewed_commit" \
  -f session_id="$session_id" \
  -f peer_envelope_base64="$(base64 <hatchery-phase-a.json | tr -d '\n')" \
  -f peer_envelope_sha256="$(sha256sum hatchery-phase-a.json | awk '{print $1}')" \
  -f peer_closure_sha256="$hatchery_closure_sha256"
```

GitHub caps the complete workflow-dispatch input payload at 65,535 characters.
The protocol therefore caps a dispatched envelope at 46,000 bytes and its
single-line base64 form at 61,500 characters. A local round trip using the
frozen no-user-ID certificate shape measured the opening envelope at 42,343
bytes and 56,460 base64 characters. If a consumer exceeds either protocol cap,
revise and re-review the transport instead of truncating or uploading secret
material.

The qualification job then:

1. proves a GitHub-hosted macOS 15 ARM64 runner and records `ImageOS`,
   `ImageVersion`, `RUNNER_ARCH`, `RUNNER_ENVIRONMENT`, `sw_vers`, Xcode, and
   build-tool identities;
2. verifies the signed Sequoia tags and exact commits, enforces both observed
   signer fingerprints, and proves each pre-patch archive matches the signed
   commit tree;
3. verifies the retained patches, final 2.4.1 locks, OpenSSL signature and
   source, exact active Homebrew/core formula revision and bytes, and OpenSSL
   bottle before installing dependencies;
4. runs the complete upstream `sq` and `sqv` suites against OpenSSL 3.5.8;
5. copies both exact formulae into the ephemeral tap, creates a local unsigned
   Git commit, and requires the clean committed blobs and working-tree bytes to
   match `candidate.json` before building and bottling either formula;
6. proves that a wrong executable digest leaves the selector absent, then
   selects only exact Cellar paths;
7. rechecks the active formula and core revision, then records every on-disk
   Mach-O dependency digest and queries the live cache
   with `/usr/bin/dyld_shared_cache_util -list`; an unresolved install name is
   accepted only by exact membership in that listing, and the evidence retains
   the utility identity, listing digest, listed-name count, and used members;
8. runs generation, exact key and signature packet-shape inspection, lint,
   detached `sq` and independent `sqv` verification,
   altered-message rejection, encryption/decryption, tampered-ciphertext
   rejection without recovered output, emergency and explicit certificate
   revocation, signing- and encryption-subkey retirement, and 200 sequential
   clean lifecycles of each executable; and
9. records `runtime-closure.json`, including the source-verification receipt,
   post-build formula observation, tap commit, and live-cache observation,
   signs its exact SHA-256 as phase B's producer closure, and uploads the
   unchanged closure beside `macos-ci-phase-b.json` while keeping the macOS
   secret certificate only in the still-running job.

## Complete the live return

While the original macOS job is waiting, the coordinator downloads the
phase-B artifact whose name contains the exact qualifier run ID. It reviews the
sibling `runtime-closure.json` against the candidate revision, runner, tap,
tools, executable and dylib identities, and shared-cache observations, then
gives #148 that file's exact SHA-256 as the expected macOS closure. The
coordinator never derives the expected value from the envelope field alone.

#148 loads the same exact closure bytes and requires their SHA-256 to equal
both the coordinator-supplied value and phase B's signed
`producer_closure_sha256`. It then verifies the control signature, protocol,
fresh session, phase-A parent digest, exact composite certificate/signature
shapes, and message signature before encryption. Using the same retained
Hatchery secret from its open phase, it decrypts and tamper-tests
`ciphertext-to-hatchery.pgp`, then encrypts the fixed message to the inspected
macOS certificate.

#148 creates `results/hatchery.json` with exact SHA-256 and size records for
all seven finite exchange artifacts: the fixed message, both public
certificates, both message signatures, and both ciphertexts. It places that
result and `ciphertext-to-macos-ci.pgp` in phase C, sets the exact phase-B
envelope digest as the parent, and signs the canonical phase-C transcript with
the retained phase-A signing key. It then removes its disposable secret,
Sequoia home, plaintext derivatives, altered input, and tampered ciphertext.
Only after cleanup succeeds may it release the already signed phase-C bytes;
if cleanup fails, it releases nothing. This ordering is what makes the
disposable-job lifecycle feasible without inventing a later signer whose key
was already destroyed.

The coordinator relays those unchanged public bytes through the same workflow:

```sh
gh workflow run pq-sequoia-macos.yml \
  --ref "$reviewed_ref" \
  -f mode=publish-peer-response \
  -f candidate_commit="$reviewed_commit" \
  -f session_id="$session_id" \
  -f peer_envelope_base64="$(base64 <hatchery-phase-c.json | tr -d '\n')" \
  -f peer_envelope_sha256="$(sha256sum hatchery-phase-c.json | awk '{print $1}')" \
  -f peer_closure_sha256="$hatchery_closure_sha256" \
  -f qualifier_run_id="$qualifier_run_id" \
  -f parent_envelope_sha256="$phase_b_sha256"
```

The relay run title and artifact name contain the exact session ID, qualifier
run ID, and phase-B digest. At selection, the original job asks the maintained
validator to traverse the workflow-scoped REST endpoint:

```sh
scripts/pq-sequoia-macos record-relay-observation \
  --repository "$GITHUB_REPOSITORY" \
  --stage selection \
  --session-id "$session_id" \
  --qualifier-run-id "$qualifier_run_id" \
  --phase-b-sha256 "$phase_b_sha256" \
  --expected-commit "$reviewed_commit" \
  --output relay-observation-selection.json
```

The command uses `GET`, `per_page=100`, and `gh api --paginate` on
`/repos/{owner}/{repo}/actions/workflows/pq-sequoia-macos.yml/runs`. It sends
none of the named search filters. It validates and normalizes each projected
page as it arrives, including each run's `run_attempt`, while retaining
unrelated run identities and normalized records only in a temporary on-disk
index. Identical repeats of one positive database ID and run attempt count once
and increment the repeated-record count. A different attempt of the same run
remains a distinct observation; conflicting values for one database ID and run
attempt reject the traversal.

The command matches the exact title before considering state. More than one
distinct match rejects, whether the second run is queued, pending, in-progress,
completed unsuccessfully, or completed successfully. After the complete
traversal, a duplicate writes the value-free observation with every distinct
match, complete query coverage, no selected run, and an explicit rejected
outcome and reason before the command returns nonzero. The workflow copies only
that allowlisted record into a failure-only relay artifact. A matching
`run_attempt` greater than 1 is rejected and retained the same way, even when it
is the only matching database ID. The failure upload excludes private state and
does not upload the success-only qualification artifact. Zero matches or one
unfinished or unsuccessful first-attempt match produces
`selection_ready=false`, so the workflow continues polling. One completed
successful first-attempt match is selected and still must pass the exact relay
metadata validator before download. The attempt, event, and commit restrictions
are applied locally to that sole match.

After phase C is authenticated and the live exchange closes, the workflow
queries again and invokes the same command with `--stage final` and
`--selected-run-id`. Final evidence proceeds only when the sole title match is
the selected completed-successful run. The selection and final records are
retained as `relay-observation-selection.json` and
`relay-observation-final.json`; each contains the structured exchange binding,
selected run ID, each matching run attempt, endpoint, page size, successful
pagination completion, page and record counts, unique and repeated record
counts, absence of named search filters, and every distinct exact-title run
attempt. If the final traversal rejects a duplicate or rerun, the failure-only
artifact retains the byte-identical successful selection observation and the
rejected final observation. Its upload allowlist contains only those two fixed
paths.

Successful end of pagination and exit zero from `gh api` are mandatory. A
provider or CLI error, timeout, interruption, malformed page, malformed run,
conflicting observation, absent selected run at the final check, or incomplete
traversal rejects without leaving an observation. A completed duplicate or
rerun traversal leaves only the fixed rejected observation files described
above. The 60-second query timeout is an operational fail-closed bound, not an
accepted page or record cutoff. The relay window remains 45 minutes. Ambiguity,
revision drift, or any mismatch rejects the session and cleans up; a later job
cannot resume it because the required secret no longer exists.

Submissions after the final check are outside the guarantee. These traversals
are not a permanent or global uniqueness guarantee, are not an atomic provider
snapshot, and make no claim about runs the provider does not return.

Revocation packets do not cross platforms. The accepted contract requires
each side's emergency certificate, retired certificate, retired signing
subkey, and retired encryption subkey transitions, but cross-platform behavior
is detached-signature and encryption interoperability. Each subkey transition
uses the same locally merged artifact on both sides of its retirement time.
Before retirement, the signing pair creates and verifies a fresh detached
signature, while the encryption pair creates fresh ciphertext and decrypts
byte-for-byte to the fixed message. After retirement, the same operation with
the same artifact must reject and leave no output path. A passed record is
written only after the complete pair succeeds. Results retain only pass/fail
classifications, packet sizes and SHA-256 values, and scrubbed diagnostics.

## Completion evidence

The final macOS artifact contains the candidate and protocol, fixed message,
source-verification receipt, the exact `sq`, `sqv`, and OpenSSL GnuPG status
preimages, all three envelopes, both peer results with identical seven-artifact
maps, exact relay-run metadata, both bounded relay observation records, local
results, bottle metadata, the tap closure, the runtime closure, and
`SHA256SUMS`. The runtime closure does not contain its own digest; phase B and
the peer results bind that digest. Envelope, result, closure, observation, and
index digests remain separate from the reciprocal map because a container
cannot contain its own digest.
Acceptance still requires #258 to reconcile the #147 and #148 evidence, a
fresh independent review tied to the executed revision, the exact workflow
run and runner image, and a fresh #149 decision.

Record these limits with every run: GitHub CI does not qualify a personal Mac,
persistent installation, keychain or vault behavior, physical hardware,
custody, concurrent OpenSSL shutdown behavior beyond upstream tests, or
production authority. System libraries resident only in Apple's dyld shared
cache have names but no on-disk bytes for the workflow to hash.

The evidence consumers are the coordinator for source/runtime reconciliation,
dotfiles #148 for the reviewed protocol and independent expected-closure
comparison, and dotfiles #149 for fresh acceptance after both runtime lanes
deliver. A source test, preflight, or successful workflow is evidence only at
its tested layer. Root hands #148 the reviewed source revision, exact protocol
digest, exact phase-B companion closure, and invocation condition only after a
fresh independent review is clean; #149 remains blocked until the two live
runtime results reconcile. This ordering has no dependency back from #147 to a
#148 or #149 acceptance result.

## Public references

- [GitHub-hosted runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [GitHub Actions variables](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)
- [GitHub workflow syntax and dispatch limits](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub runner image identity](https://github.com/actions/runner-images)
- [OpenSSL releases and signing certificate](https://openssl-library.org/source/)
- [Homebrew `openssl@3.5`](https://formulae.brew.sh/formula/openssl%403.5)
- [RFC 9980](https://www.rfc-editor.org/rfc/rfc9980.html)
