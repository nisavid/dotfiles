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
  dotfiles #148. Its fixed [message](fixtures/v1/message.bin) is exactly 51
  bytes and has SHA-256
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

The #148 consumer must load `interop-v1.json`, record its reviewed Hatchery
candidate identity, and create `hatchery-phase-a.json`. The envelope contains
only its disposable public certificate and detached signature over the fixed
message. It records all four local revocation checks as value-free results.

The Hatchery secret certificate stays in #148's isolated temporary storage
from `hatchery-open` through `hatchery-return`. If it is destroyed before the
return phase, stop: no later rebuild can stand in for that session.

Validate the opening envelope before dispatch:

```sh
scripts/pq-sequoia-macos validate-envelope \
  --phase hatchery-phase-a \
  --session-id "$session_id" \
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
  -f peer_envelope_sha256="$(sha256sum hatchery-phase-a.json | awk '{print $1}')"
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
   executable output, records every on-disk Mach-O dependency digest, and
   leaves system shared-cache references explicitly unresolved;
5. proves that a wrong executable digest leaves the selector absent, then
   selects only exact Cellar paths;
6. runs generation, lint, detached `sq` and independent `sqv` verification,
   altered-message rejection, encryption/decryption, tampered-ciphertext
   rejection without recovered output, emergency and explicit certificate
   revocation, signing- and encryption-subkey retirement, and 200 sequential
   clean lifecycles of each executable; and
7. uploads `macos-ci-phase-b.json` while keeping the macOS secret certificate
   only in the still-running job.

## Complete the live return

While the original macOS job is waiting, #148 downloads and validates
`macos-ci-phase-b.json`. Using the same retained Hatchery secret from its open
phase, it verifies the macOS signature and altered-message rejection, decrypts
and tampers with `ciphertext-to-hatchery.pgp`, then encrypts the fixed message
to the macOS public certificate. It finalizes `hatchery-phase-c.json`, cleans
its disposable secret material, and gives the coordinator the exact response
bytes and lowercase SHA-256.

The coordinator relays those unchanged public bytes through the same workflow:

```sh
gh workflow run pq-sequoia-macos.yml \
  --ref "$reviewed_ref" \
  -f mode=publish-peer-response \
  -f candidate_commit="$reviewed_commit" \
  -f session_id="$session_id" \
  -f peer_envelope_base64="$(base64 <hatchery-phase-c.json | tr -d '\n')" \
  -f peer_envelope_sha256="$(sha256sum hatchery-phase-c.json | awk '{print $1}')"
```

The original job downloads only the response artifact for that session,
decrypts it with its still-local secret, runs the tamper-negative check, writes
the final public result, and removes the secret workspace. The relay window is
45 minutes. Timeout or any mismatch rejects the session and cleans up; a later
job cannot resume it because the required secret no longer exists.

Revocation packets do not cross platforms. The accepted contract requires
each side's emergency certificate, retired certificate, retired signing
subkey, and retired encryption subkey transitions, but cross-platform behavior
is detached-signature and encryption interoperability. Results retain only
pass/fail classifications, packet sizes and SHA-256 values, and scrubbed
diagnostics.

## Completion evidence

The final macOS artifact contains the candidate and protocol, fixed message,
both peer envelopes, local and interoperability results, bottle metadata,
runtime closure, and `SHA256SUMS`. Acceptance still requires #258 to reconcile
the #147 and #148 digest maps, a fresh independent review tied to the executed
revision, the exact workflow run and runner image, and a fresh #149 decision.

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
