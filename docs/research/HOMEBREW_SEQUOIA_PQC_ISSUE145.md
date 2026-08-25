# Homebrew Sequoia RFC 9980 qualification baseline

Verified on 2026-08-24 against Homebrew core commit
[`67a856e0a75fe0e5a822ae2d5a53538403aed8ae`](https://github.com/Homebrew/homebrew-core/commit/67a856e0a75fe0e5a822ae2d5a53538403aed8ae),
the `sequoia-sq` 1.4.0 and `sequoia-sqv` 1.5.0 release sources,
`sequoia-openpgp` 2.4.0 and 2.4.1 release notes, OpenSSL's public
documentation, and RFC 9980. This is the public-source baseline and
value-free live evidence for
[`stlz-ivan-mbp` qualification in issue #145](https://github.com/nisavid/dotfiles/issues/145),
including the software installed on that host at the time of the probe.

## Findings

1. Homebrew core currently offers stable `sequoia-sq` 1.4.0 and
   `sequoia-sqv` 1.5.0. Both have Apple Silicon bottles for macOS Tahoe,
   Sequoia, and Sonoma; their formula pages also list Intel Sonoma and Linux
   bottles. [Homebrew `sequoia-sq`](https://formulae.brew.sh/formula/sequoia-sq)
   and [Homebrew `sequoia-sqv`](https://formulae.brew.sh/formula/sequoia-sqv).
2. These are intentionally OpenSSL-backed builds. Both formulae declare
   `openssl@3`, point `OPENSSL_DIR` at that formula, disable default Cargo
   features, and enable `crypto-openssl`. The immutable
   [`sequoia-sq` formula](https://raw.githubusercontent.com/Homebrew/homebrew-core/67a856e0a75fe0e5a822ae2d5a53538403aed8ae/Formula/s/sequoia-sq.rb)
   and [`sequoia-sqv` formula](https://raw.githubusercontent.com/Homebrew/homebrew-core/67a856e0a75fe0e5a822ae2d5a53538403aed8ae/Formula/s/sequoia-sqv.rb)
   are the source of truth for that selection.
3. The formula helper `std_cargo_args` includes `--locked`, so each build uses
   the release tag's dependency lock rather than silently resolving newer
   crates. [Homebrew's Formula API](https://docs.brew.sh/rubydoc/Formula.html#std_cargo_args-instance_method).
   Both release locks resolve `sequoia-openpgp` 2.4.0:
   [`sq` lock](https://gitlab.com/sequoia-pgp/sequoia-sq/-/raw/v1.4.0/Cargo.lock)
   and [`sqv` lock](https://gitlab.com/sequoia-pgp/sequoia-sqv/-/raw/v1.5.0/Cargo.lock).
4. `sequoia-openpgp` 2.4.0 added RFC 9980 post-quantum support through both
   the OpenSSL and RustCrypto backends. OpenSSL is therefore the selected
   Homebrew backend, not the only current Sequoia backend capable of PQ
   operations. `sq` 1.4.0 separately records RFC 9980 support and adds the
   post-quantum signing and encryption algorithm controls used by the host
   probe. [`sequoia-openpgp` 2.4.0 release notes](https://gitlab.com/sequoia-pgp/sequoia/-/raw/openpgp/v2.4.0/openpgp/NEWS)
   and [`sq` 1.4.0 release notes](https://gitlab.com/sequoia-pgp/sequoia-sq/-/raw/v1.4.0/NEWS).
5. Sequoia's OpenSSL backend reports its post-quantum algorithms as supported
   only when the OpenSSL API level is at least 3.5.0. OpenSSL 3.5 introduced
   ML-KEM, ML-DSA, and SLH-DSA and is an LTS release supported through
   2030-04-08. [Sequoia's OpenSSL backend check](https://gitlab.com/sequoia-pgp/sequoia/-/blob/openpgp/v2.4.0/openpgp/src/crypto/backend/openssl/asymmetric.rs)
   and [OpenSSL 3.5 release announcement](https://openssl-library.org/post/2025-04-08-openssl-35-final-release/).
6. Homebrew's current `openssl@3` is 3.6.3. Homebrew says that the formula will
   move back to OpenSSL 3.5 LTS after 3.6 support ends. Both versions satisfy
   Sequoia's API-level gate, so the durable requirement is OpenSSL API level
   `>= 3.5.0`, not a pin to the 3.6 release line.
   [Homebrew `openssl@3`](https://formulae.brew.sh/formula/openssl@3).
7. The stable Homebrew builds carry a known dependency caveat:
   `sequoia-openpgp` 2.4.1 disables OpenSSL's `atexit` cleanup handlers because
   they can crash a process if cleanup runs while another thread still uses
   OpenSSL. The current stable `sq` and `sqv` locks still select 2.4.0, so
   successful PQ operations alone are not sufficient evidence for a durable
   production disposition. The failure was reproduced at the end of a
   short-lived `sq` test process; the fix initializes OpenSSL with
   `OPENSSL_INIT_NO_ATEXIT`.
   [`sequoia-openpgp` 2.4.1 release notes](https://gitlab.com/sequoia-pgp/sequoia/-/raw/openpgp/v2.4.1/openpgp/NEWS),
   [upstream crash report](https://gitlab.com/sequoia-pgp/sequoia/-/work_items/1251),
   and [fix commit](https://gitlab.com/sequoia-pgp/sequoia/-/commit/64fcd69642d7e4eaf7511c7e97e35347cb070efb).
8. Homebrew core has no `sequoia-sop` formula. Its
   `sequoia-chameleon-gnupg` 0.13.1 formula locks `sequoia-openpgp` 2.0.0,
   before the stable RFC 9980 implementation, so Chameleon remains a named
   GnuPG-compatibility exception rather than part of this PQ path.
   [Homebrew `sequoia-chameleon-gnupg`](https://formulae.brew.sh/formula/sequoia-chameleon-gnupg)
   and [its release lock](https://gitlab.com/sequoia-pgp/sequoia-chameleon-gnupg/-/raw/v0.13.1/Cargo.lock).
   The moving `HEAD` sources are also unnecessary for feature availability and
   do not meet the production path's immutable-release requirement.

## Live host evidence

The read-only and disposable probe ran on an Apple Silicon Mac with macOS
26.6.2. No package, command path, persistent Sequoia state, configuration, or
production key material changed.

- Homebrew had poured the stable Apple Silicon bottles for `sequoia-sq` 1.4.0,
  `sequoia-sqv` 1.5.0, and `openssl@3` 3.6.3. The installed executables report
  `sequoia-openpgp` 2.4.0 with the OpenSSL 3.6.3 backend.
- The installed receipts reported the `arm64_tahoe` bottles from Homebrew core
  tap revision `659358b41e73f70184a97fea7e9d2cc64e9caa50`. The `sq` formula
  source checksum was
  `b271ab7f09d84d8145edef732ee5532436181e00fba2d1f7a7a44571b7d5cd64`
  and its bottle SHA-256 was
  `e9e61d139b48df4a934d57d48e4cdb18d6e524204121ce04018a9aa7a2cb6fc5`.
  The `sqv` formula source checksum was
  `13cae35b5b9ce36e18e8f29325ba8e0019659bd4678509dc07ea0f50781c9825`
  and its bottle SHA-256 was
  `3ea889ab5ab37e22d8f432bfbe0057d0e01e89659995f514bd0a118af31495b1`.
  The `openssl@3` bottle SHA-256 was
  `2d995a1bbbd8e6ee6a9042990dde87e7321d1ddd5716ffee53b140d23cb9f92f`.
- The `sq` and `sqv` executable SHA-256 digests were respectively
  `ea40731004cd0b803871d404ed401df8cc28f4e9cf754ce76f629a8d371f4e73`
  and
  `bc922bb4fd836d2e50826bfe12d6a894a7cf3d7fa1b16ffa36607bdc2ce464cc`.
  Dynamic-link inspection resolved both tools to Homebrew's `libssl.3` and
  `libcrypto.3`; Homebrew's linkage checks passed.
- OpenSSL exposed ML-DSA-44/65/87 and ML-KEM-512/768/1024. In an isolated
  temporary Sequoia home, `sq` generated a one-day version-6 certificate with
  an ML-DSA-65+Ed25519 certify-only primary, a matching signing subkey, and an
  ML-KEM-768+X25519 encryption subkey. Certificate linting, detached signing,
  `sq` and `sqv` verification, and encryption/decryption all passed. In two
  separate isolated certificate stores, importing either the emergency
  revocation or explicit retirement revocation changed the matching
  certificate from usable to unusable; `--gossip --unusable` then exposed its
  revoked state.
- Detached-signature verification and ML-KEM encryption/decryption passed in
  both directions between the Mac bottles and the reviewed Hatchery candidates
  at arch-pkgs revision
  `bfe5a3928bbe3e6d1c28d7131aac12da3642764e`: Mac `sq` to candidate `sqv`,
  candidate `sq` to Mac `sqv`, candidate `sq` encryption to a Mac-generated
  key, and Mac `sq` encryption to a Hatchery-generated key. The candidate
  package SHA-256 digests were
  `c4bf627fd20241449dce9274a15ecdc1a0f66cf9c235ca248b8fe9097381fe17`
  for `sequoia-sq-pqc` and
  `2e8df85ae2aa8acdf662f3c63b7a7ba32214fd9a52252acbc34e40cdd08b62b3`
  for `sequoia-sqv-pqc`.
- The Mac-generated certificate, signature, and message had matching sender
  and Hatchery-receiver SHA-256 digests `6c18f573712c6a4736484fed2bc7969951d903e8a499abc69aeddebee5fe7277`,
  `e86ab1536c0a691ef1e767c4e9f3a7a9bd4af0904019fffdd40343e116d1b2f9`,
  and `6d9238f3212624db1ccc90e40a193da9310c411833b9fbaf1a6dfb3882320f16`.
  The Hatchery-produced ciphertext for that key matched on the Mac at
  `c3f6c88a924e46b8fd973b15abed930a0e1aeb3f28e0611a6737e21d1cabcd76`.
- The Hatchery-generated certificate, signature, and message had matching
  sender and Mac-receiver SHA-256 digests
  `3b6992b96c7ee7802d38e869f25b6e37de7e1c5aad963ad4836e6a9edab9f565`,
  `e7bfc675fc9f7918fcaebedcc031fb29f5ed020640765e795d475eb8bb62b52b`,
  and `37478d1b11c3edae52f4d5dffe9c125e7043a718b75077e4dc94f7a04df14f52`.
  The Mac-produced ciphertext for that key matched on Hatchery at
  `2c3362d0e290609757ff352e5c8f12e9e0f47d79563bb46f19132dcc9fc8c15a`.
- A bounded diagnostic then completed 50 fresh `sq` sign, `sq` verify, and
  `sqv` verify process lifecycles without reproducing the crash. Sequential
  lifecycles do not exercise the reported concurrency condition and provide no
  basis for waiving the 2.4.1 fix.

All disposable key, signature, ciphertext, revocation, extracted-package, and
temporary-home material was removed after the probes.

### Probe command record

The probe bound `PATH` to the Homebrew executables, set `SEQUOIA_HOME` to a
mode-0700 temporary directory, and used only paths beneath that directory. The
functional sequence was:

```sh
sq key generate \
  --profile rfc9580 \
  --signing-algorithm mldsa65-ed25519 \
  --encryption-algorithm mlkem768-x25519 \
  --cannot-authenticate --can-sign --can-encrypt universal \
  --without-password --expiration 1d --no-userids --own-key \
  --output "$probe_dir/key.pgp" \
  --rev-cert "$probe_dir/emergency-revocation.pgp"
sq key delete \
  --cert-file "$probe_dir/key.pgp" \
  --output "$probe_dir/cert.pgp"
sq cert lint --cert-file "$probe_dir/cert.pgp"

sq sign \
  --signer-file "$probe_dir/key.pgp" \
  --signature-file "$probe_dir/message.sig" \
  "$probe_dir/message.txt"
sq verify \
  --signer-file "$probe_dir/cert.pgp" \
  --signature-file "$probe_dir/message.sig" \
  "$probe_dir/message.txt"
sqv \
  --keyring "$probe_dir/cert.pgp" \
  --signature-file "$probe_dir/message.sig" \
  "$probe_dir/message.txt"

sq encrypt \
  --profile rfc9580 \
  --for-file "$probe_dir/cert.pgp" \
  --without-signature \
  --output "$probe_dir/message.pgp" \
  "$probe_dir/message.txt"
sq decrypt \
  --recipient-file "$probe_dir/key.pgp" \
  --output "$probe_dir/decrypted.txt" \
  "$probe_dir/message.pgp"
cmp "$probe_dir/message.txt" "$probe_dir/decrypted.txt"

sq key revoke \
  --cert-file "$probe_dir/key.pgp" \
  --reason retired \
  --message "Disposable qualification certificate retired" \
  --output "$probe_dir/retired.pgp"
sq inspect "$probe_dir/emergency-revocation.pgp"
sq inspect "$probe_dir/retired.pgp"

# Repeat in a separate isolated SEQUOIA_HOME for each revocation.
sq cert import "$probe_dir/cert.pgp"
sq cert list --cert "$fingerprint"
sq cert import "$revocation_file"
! sq cert list --cert "$fingerprint"
sq cert list --gossip --unusable --cert "$fingerprint"
```

For each cross-host signature check, only the disposable public certificate,
detached signature, and message crossed the host boundary; the disposable
secret key stayed on its generating host. The receiving host invoked its
qualified `sqv` against those three files. Each encryption check transferred a
public certificate to the encrypting host and returned the ciphertext to the
secret key's host for decryption. Exit status zero, matching sender/receiver
artifact hashes, exact plaintext comparison, algorithm and revocation-state
inspection, package/executable digests, and cleanup were the recorded outputs;
no secret values were retained.

## RFC 9980 acceptance target

RFC 9980 is an IETF Standards Track extension to RFC 9580. A conforming
implementation must support composite ML-DSA-65+Ed25519 signatures and
ML-KEM-768+X25519 encryption. Both signature components must verify, and both
KEM decapsulations must succeed. With the single exception that
ML-KEM-768+X25519 may appear on a version-4 encryption subkey, these algorithms
belong on version-6 or newer keys and certificates. [RFC 9980 Sections 1.4,
2.1, 3.2, and 3.5](https://www.rfc-editor.org/rfc/rfc9980.html).

For issue #145, the minimum disposable acceptance flow is therefore:

- show that the installed `sq` and `sqv` came from the intended Homebrew
  formulae and record their versions and bottle identities;
- show the actual OpenSSL backend/API level and dynamic linkage to Homebrew's
  `libcrypto`, rather than inferring them from formula metadata;
- generate and inspect an isolated version-6 certificate using
  ML-DSA-65+Ed25519 for signing and ML-KEM-768+X25519 for encryption;
- create and verify a detached signature with `sq`, then independently verify
  it with `sqv`;
- encrypt and decrypt a disposable message through the composite KEM;
- repeat detached-signature and encryption/decryption interoperability in both
  host directions, with matching transfer-artifact digests;
- exercise certificate linting and revocation without importing anything into
  the ordinary user key or certificate stores; and
- repeat process startup and shutdown as a diagnostic for the 2.4.0 OpenSSL
  cleanup defect, without treating a clean run as a substitute for carrying
  the 2.4.1 fix.

## Disposition

The Homebrew route is structurally capable of the required RFC 9980 profile:
the stable formulae select the correct backend and an adequate OpenSSL API.
The installed bottles passed the complete disposable functional matrix and
bilateral detached-signature verification. They are nevertheless not accepted
for durable production use because their stable dependency locks predate the
2.4.1 OpenSSL cleanup fix. A non-crashing test run cannot prove that race
absent. The upstream reports identify a process-exit reliability defect; they
do not identify a cryptographic-correctness or key-corruption defect.

Require `sequoia-openpgp` 2.4.1 or later for the production disposition. If
Homebrew updates the stable formulae accordingly, re-run the same acceptance
flow and the full bidirectional host-interoperability matrix against the
immutable replacement bottles. This is the preferred path, but it uses the
same identity, promotion, dependency-retention, and rollback controls as the
fallback below. Treat replacement core bottles as candidates through explicit
Cellar paths until their exact identities are accepted.

If the production ceremony cannot wait for Homebrew core, use versioned,
keg-only private-tap formulae for `sq` and `sqv`. Each formula must pin the
upstream release source and checksum, carry a reviewed lockfile update to
`sequoia-openpgp` 2.4.1 or later, select `crypto-openssl`, require OpenSSL API
level 3.5 or later, and publish a bottle digest. Invoke the candidate through
its explicit keg path until acceptance so it cannot silently replace the core
commands. Record the tap commit, formula checksum, source checksum, lockfile
diff, bottle digest, executable digest, and dynamic linkage in the registry.
Record and retain the accepted `openssl@3` keg version, formula/source
checksum, bottle digest, and dynamic-library digests as part of the runtime
identity; any dependency change requires requalification.

Updates are manual promotions: build or fetch one immutable candidate, run the
full local matrix plus bilateral signature and encryption interoperability,
and change the accepted identity only after cross-host review. Retain the last
accepted `sq`, `sqv`, and OpenSSL bottles, kegs, and metadata. An explicit
operational selector or wrapper identifies the accepted keg paths; Homebrew's
shared linked commands are not the production authority. On an identity
mismatch, backend/API mismatch, operation failure, or crash, switch that
selector back to the retained known-good runtime closure. For the first
rollout, where no earlier 2.4.1-or-newer closure exists, rollback means
disabling the production workflow; it must not silently fall back to the
rejected 2.4.0 bottles.

SOP is not required for issue #145's host acceptance path. This qualification
establishes the required operations with `sq` and verification with `sqv`; it
does not select their CLI as a durable application or CI integration contract.

The formulae's built-in tests do not close this gap. `sequoia-sq` tests only
version output and packet armoring, while `sequoia-sqv` verifies a classical
Ed25519 fixture. Neither test exercises RFC 9980 key generation, composite
signing, composite verification, encryption, decryption, revocation, or the
reported concurrent-use-at-exit condition. The `sqv` test does initialize the
selected OpenSSL backend and exit; a clean exit in that sequential case cannot
waive the upstream fix. The formula sources linked above define those test
bodies.
