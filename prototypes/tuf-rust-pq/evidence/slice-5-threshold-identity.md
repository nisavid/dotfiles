# Composite threshold-identity correction

The revised first executable slice prevents one RFC 9980 composite signing key
from contributing more than once to a Tough signature threshold through either
root or delegation verification. It also rejects undefined flattened fields in
the provisional OpenPGP key shape. The accepted cryptographic profile,
publisher hook, canonical signed bytes, and TUF state-machine paths are
unchanged.

## Historical review boundary

Independent review of the frozen candidate reported the valid P1
`RR1-THRESHOLD-IDENTITY-001`. Its result has SHA-256
`8bbe35403b38073e9673319270cb6abb7b3875b4affc7fb2b5cb03b288524803`.
The [original execution record](slice-3-red-green.md) remains unchanged and is
historical: it covers repeated identical TUF key IDs, not distinct IDs that
project the same signing key.

The historical patch had SHA-256
`6c8563058fceb8aabe26ab0afb49297cc53d800c1104ebb4ea258aa47cc80c1c`.
It verified an OpenPGP key without using its flattened fields, while Tough
included those fields in the canonical key object hashed into the TUF key ID.

## Behavioral red

The counterexamples used Tough's public metadata types and public role
verifiers. Key maps were serialized and reparsed, so Tough checked that every
map key was the correctly derived ID of its value.

With the historical patch and test candidate
`069d768b74214b64d7faaf7df9893df5a8d1f8ef163c9d6b2fa60f0fffdc6bdb`,
two root key objects contained the same certificate and differed only by one
undefined outer field. One detached packet was relabeled under both derived
IDs. The targeted locked, offline test exited 101:

```text
running 1 test
one composite signing key must not satisfy threshold 2: ()
test root_rejects_distinct_tuf_ids_for_one_composite_signing_key ... FAILED
test result: FAILED. 0 passed; 1 failed
```

A stronger delegation counterexample used two profile-valid certificate
projections with no JSON extensions. The second projection added an unbound
User ID packet but retained the same composite signing-key fingerprint. With
test candidate
`0132d73f1be31698c2a2cb56b101a923e48add3a7bf5b633af19fb4c193c6693`,
`Delegations::verify_role` accepted the relabeled packet twice and the targeted
test exited 101:

```text
one composite signing key must not satisfy delegated threshold 2: ()
test delegations_reject_distinct_tuf_ids_for_one_composite_signing_key ... FAILED
test result: FAILED. 0 passed; 1 failed
```

Finally, test candidate
`3bd4088f21de2c9bfedb9ff5bf4e7535b2eb5d7826de94aa97f2081b744c607a`
showed that an undefined OpenPGP field still verified at threshold 1:

```text
undefined OpenPGP key fields must not verify: ()
test root_rejects_undefined_openpgp_extensions ... FAILED
test result: FAILED. 0 passed; 1 failed
```

Fixture-setup and compile failures encountered while constructing these tests
are not treated as behavioral red evidence.

## Correction boundary

`Key::verify` now returns a domain-separated threshold identity only after a
signature verifies:

- Existing RSA, Ed25519, and ECDSA keys retain their authorized TUF key ID.
- This OpenPGP profile returns the verified v6 composite signing-key
  fingerprint.
- Root and delegation verification count each returned identity once.
- A nonempty flattened field on the OpenPGP key or its `keyval` prevents that
  key from verifying.

The fingerprint is the signature's sole v6 issuer, is required to match the
certificate's sole policy-valid algorithm-30 signing key, and is returned only
after Sequoia reports `GoodChecksum`. This identity says nothing about operator,
custody, or independence of the Ed25519 and ML-DSA-65 components.

The complete patch has SHA-256
`e2070c8deba02f51c9c47e2bf868da52cd761847a6e0ba6ed7b9bfdad737e42e`.
It is 11,405 bytes and changes three upstream files with 189 insertions and 15
deletions. Relative to the historical 7,673-byte, two-file patch, it adds the
shared threshold-identity handling in `tough/src/schema/verify.rs`; it adds no
dependency and leaves `Cargo.lock` unchanged.

## Green and observable result

The final test source has SHA-256
`9057b159657ebc7113d729b87cf405fc2474fa55e51211bfdf2b0184cbc5965f`.
The locked, offline integration command exited 0 with four public-seam tests:

```text
running 4 tests
test delegations_reject_distinct_tuf_ids_for_one_composite_signing_key ... ok
test root_rejects_undefined_openpgp_extensions ... ok
test root_rejects_distinct_tuf_ids_for_one_composite_signing_key ... ok
{"canonicalSignedBytes":36589,"compositeSigningKeyThresholdContributions":1,"delegatedDistinctTufIdsForOneCompositeSigningKeyRejected":true,"distinctTufIdsForOneCompositeSigningKeyRejected":true,"duplicateCompositeSignatureRejected":true,"ed25519ComponentCorruptionRejected":true,"hash":"SHA-512","issuerFingerprint":"C15250DD7234E11819784A9791DF1F039094760F66926108A5297C6AC8D320B0","keyId":"631ebaf3a756e8669084937f72d86aa3d6dbe18675cec42c5e4d96e8c196f330","keyType":"openpgp-rfc9580","mlDsa65ComponentCorruptionRejected":true,"outerReformatVerified":true,"publicKeyAlgorithm":30,"publicProjectionBytes":17935,"scheme":"openpgp-rfc9980-ml-dsa-65+ed25519-sha512","signaturePacketBytes":3464,"signaturePacketCount":1,"signatureType":0,"signatureVersion":6,"syntheticIndependence":"one generated composite key; no operator, custody, or underlying-key independence claim","thresholdIdentity":"verified-v6-openpgp-signing-key-fingerprint","thresholdTwoSatisfiedByOneCompositeKey":false,"undefinedOpenPgpExtensionsRejected":true,"verified":true}
test publisher_and_verifier_require_both_rfc9980_components ... ok
test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

The complete combined output from that same process, including the generated
fingerprint and key ID above, has SHA-256
`3e78c51fd9a86d41ea2fb0166153949bc47c1596aed6aa67eccb1c2a7324d5c0`.
It is retained in coordinator scratch evidence. Keeping the values from one
process avoids mixing randomized fixture identities across records.

## Final checks and limits

- `cargo test --locked --offline`: passed, including four integration tests and
  doc tests.
- `cargo clippy --locked --offline --all-targets -- -D warnings`: passed.
- Explicit Rustfmt checks for every task-authored Rust file: passed.
- Prototype and patched-source `git diff --check`: passed.
- The captured patch matched the modified Tough source byte-for-byte and passed
  `git apply --check` against pristine Tough commit
  `98d8eb8b2ce63515d9b4981c938ef6453c5b5771`.

Execution reused the inspected 189-package graph: 184 verified registry
archives and five path packages. No dependency changed or needed reinspection.
Commands ran with an empty environment, scratch-only writable build paths,
`--locked --offline`, and no credentials or production data. The host still
could not create a private Bubblewrap network namespace, so the observed run
shared the parent harness's separately restricted network namespace. Portable
replay requires either a working private network namespace or an independently
verified network-denied parent.

This result is Linux-only and awaits independent review of the revised
candidate. It does not complete all-role metadata, caller-supplied accepted
time, durable refresh or root rotation, held-byte policy composition, the POUF
draft, macOS qualification, or operator/custody independence.
