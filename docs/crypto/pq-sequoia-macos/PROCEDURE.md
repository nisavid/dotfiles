# Qualify the PQ Sequoia macOS candidate

This procedure builds and exercises the reviewed `sq` 1.4.0 and `sqv` 1.5.0
candidate on a fresh GitHub-hosted `macos-15` runner. It records public,
value-free evidence; it does not install a runtime on a personal Mac or grant
production, custody, publication, or acceptance authority.

Use it when an immutable application, lock, formula, OpenSSL, bottle,
executable, linked-library, runner-image, or procedure identity changes. The
candidate remains disabled until the complete local and live bidirectional
matrix succeeds at one reviewed revision and receives separate acceptance.

## Maintained inputs

- [`candidate.json`](../../../packaging/homebrew/pq-sequoia-macos/v1/candidate.json)
  fixes the application tags and commits, source and formula bytes, retained
  lock patches, final lock digests, release signers, OpenSSL source and signer,
  the Homebrew/core formula revision, and the Apple Silicon Sequoia bottle.
- [`interop-v1.json`](interop-v1.json) defines the four-phase exchange with
  dotfiles #148. Its review-candidate SHA-256 is
  `111643f12bde30782c15447f11df8e5bc3a90f9dda6e259c30f02525ab20ed33`.
  Its fixed [message](fixtures/v1/message.bin) is exactly 51 bytes and has SHA-256
  `6be8c2fe3154649151aacd41f35dd6a212881e627acca131fe3f0101b14f4337`.
- [`pq-sequoia-macos`](../../../scripts/pq-sequoia-macos) validates those
  inputs, executes the local matrix, controls exact-keg selection, records the
  Mach-O closure, and opens and closes the live exchange.
- [`pq-sequoia-macos.yml`](../../../.github/workflows/pq-sequoia-macos.yml) is
  manual-only. It has no push, pull-request, schedule, or release trigger.

The selected OpenSSL closure is Homebrew `openssl@3.5` 3.5.8, not the
preflight's OpenSSL 3.6.4 proposal. OpenSSL lists 3.5 as LTS through 2030-04-08,
and Homebrew provides a keg-only 3.5 formula with an Apple Silicon Sequoia
bottle. The workflow verifies the official detached release signature, source,
formula, and bottle bytes before use.

## Validate the checked-in surface

Run this after any edit to the procedure, protocol, formulae, or lock patches:

```sh
scripts/pq-sequoia-macos validate-static --root .
python3 -m unittest tests.test_pq_sequoia_macos
```

The command fails closed on any formula, patch, message, or manifest mismatch.
The formulae embed the same reviewed patch bytes retained beside them; the test
and command require the two copies to remain byte-identical.

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
2. verifies the signed Sequoia tags and exact commits, release archives,
   retained patches, final 2.4.1 locks, OpenSSL signature and source, pinned
   Homebrew formula, and OpenSSL bottle;
3. runs the complete upstream `sq` and `sqv` suites against OpenSSL 3.5.8;
4. builds and bottles both keg-only formulae, proves the backend and API from
   executable output, records every on-disk Mach-O dependency digest, allows
   unresolved names only in the absolute `/usr/lib/`,
   `/System/Library/Frameworks/`, and
   `/System/Library/PrivateFrameworks/` shared-cache namespaces, and rejects
   every other unresolved dependency;
5. proves that a wrong executable digest leaves the selector absent, then
   selects only exact Cellar paths;
6. runs generation, exact key and signature packet-shape inspection, lint,
   detached `sq` and independent `sqv` verification,
   altered-message rejection, encryption/decryption, tampered-ciphertext
   rejection without recovered output, emergency and explicit certificate
   revocation, signing- and encryption-subkey retirement, and 200 sequential
   clean lifecycles of each executable; and
7. authenticates phase A, signs a parent-chained phase-B transcript, and
   uploads `macos-ci-phase-b.json` while keeping the macOS secret certificate
   only in the still-running job.

## Complete the live return

While the original macOS job is waiting, #148 downloads the phase-B artifact
whose name contains the exact qualifier run ID. It verifies the phase-B
control signature, reviewed macOS closure, protocol, fresh session, phase-A
parent digest, exact composite certificate/signature shapes, and message
signature before encryption. Using the same retained Hatchery secret from its
open phase, it decrypts and tamper-tests `ciphertext-to-hatchery.pgp`, then
encrypts the fixed message to the inspected macOS certificate.

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

The relay run title and artifact name contain the exact qualifier run ID and
phase-B digest. The original job requires exactly one successful run with that
title, validates its database ID and head SHA against the reviewed qualifier
commit, and retains that metadata before downloading. It then authenticates
phase C under the phase-A certificate, reconciles every Hatchery artifact-map
entry with its own observation, decrypts with its still-local secret, runs the
tamper-negative check, writes both public results, and removes the secret
workspace. The relay window is 45 minutes. Timeout, ambiguity, revision drift,
or any mismatch rejects the session and cleans up; a later job cannot resume it
because the required secret no longer exists.

Revocation packets do not cross platforms. The accepted contract requires
each side's emergency certificate, retired certificate, retired signing
subkey, and retired encryption subkey transitions, but cross-platform behavior
is detached-signature and encryption interoperability. Results retain only
pass/fail classifications, packet sizes and SHA-256 values, and scrubbed
diagnostics.

## Completion evidence

The final macOS artifact contains the candidate and protocol, fixed message,
all three envelopes, both peer results with identical seven-artifact maps,
exact relay-run metadata, local results, bottle metadata, runtime closure, and
`SHA256SUMS`. Envelope, result, and index digests are retained separately from
the reciprocal map because a container cannot contain its own digest.
Acceptance still requires #258 to reconcile the #147 and #148 evidence, a
fresh independent review tied to the executed revision, the exact workflow
run and runner image, and a fresh #149 decision.

Record these limits with every run: GitHub CI does not qualify a personal Mac,
persistent installation, keychain or vault behavior, physical hardware,
custody, concurrent OpenSSL shutdown behavior beyond upstream tests, or
production authority. System libraries resident only in Apple's dyld shared
cache have names but no on-disk bytes for the workflow to hash.

## Public references

- [GitHub-hosted runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [GitHub Actions variables](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)
- [GitHub workflow syntax and dispatch limits](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub runner image identity](https://github.com/actions/runner-images)
- [OpenSSL releases and signing certificate](https://openssl-library.org/source/)
- [Homebrew `openssl@3.5`](https://formulae.brew.sh/formula/openssl%403.5)
- [RFC 9980](https://www.rfc-editor.org/rfc/rfc9980.html)
