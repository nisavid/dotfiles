# Cycle 2 OpenPGP profile-boundary correction

## Boundary decision

The active `RR2-CHECKPOINT-OPENPGP-PROFILE-BOUNDARY` is resolved at the
shared metadata key-map ingestion boundary. Every provisional OpenPGP key in a
Root or Delegations key map must satisfy the closed profile before the
containing metadata value can be constructed, including keys that no role
authorizes and no signature uses. `Key::verify` retains the same validation as
defense for keys constructed directly in memory.

This is the earliest common boundary already shared by Root and Delegations.
It closes the unused-key acceptance path without changing key-ID derivation,
canonical signed bytes, the accepted RFC 9980 certificate and signature
profile, threshold identity, or the root and delegation verification state
machines. A signer-local check alone cannot enforce the settled requirement
because metadata may contain provisional OpenPGP keys that verification never
selects.

The frozen Cycle 2 review inputs and outputs remain historical and unchanged.

## Finding dispositions

- `RR2-OPENPGP-EXTRA-VALIDATION-001` is corrected pending independent review.
  `deserialize_keys` now validates the provisional OpenPGP profile before
  calculating or inserting every key ID. Root and Delegations both use this
  deserializer. `Key::verify` calls the same validator for directly constructed
  keys.
- `RR2-BEHAVIORAL-RED-PROVENANCE-001` is corrected. The historical evidence is
  explicitly labeled as summary material below and in
  [the Slice 5 record](slice-5-threshold-identity.md). A new reproducible
  red/green bundle is retained under new names.
- `RR2-SHARED-VERIFY-COMPATIBILITY-EVIDENCE-001` is now corrected pending
  independent review. The applicable pinned Tough suite passed, and focused
  Root and Delegations ECDSA verification regressions cover its precise
  conventional-key gap. See the
  [current compatibility record](current-compatibility.md). The blocked state
  recorded later in this file remains the historical Cycle 2 checkpoint.

## Historical provenance correction

The retained Slice 5 event stream has SHA-256
`9c24fd139b1589654fa5a5d9f7f091979ad64a5961760977c568aaa090697b46`.
Its completed command events preserve the exact command, complete output, and
exit status for the root alias, delegation alias, and signer-used undefined
field reds. The stream also records the candidate hashes. Its file-change
events contain only paths, however; the complete red source bytes were not
archived separately. The older behavioral-red narratives and excerpts are
therefore historical summaries, not reproducible raw bundles. No source was
reconstructed from those narratives.

## New reproducible red and green

The new counterexamples put an independently generated provisional OpenPGP key
into a metadata key map while a different clean key is the only authorized
threshold signer. Both undefined-field placements have correctly derived key
IDs. Root metadata and Targets metadata containing Delegations are serialized
through their public schema types; the clean signature is also accepted before
the containing metadata is reparsed.

The red stage used test source
`2a712506b5dc369513cdea039c969be8c5bb77e9b166f191c49741f7ee3ea4c4`
and historical patch
`e2070c8deba02f51c9c47e2bf868da52cd761847a6e0ba6ed7b9bfdad737e42e`.
The hash-preflighted targeted command exited 101: both
`root_rejects_unused_undefined_openpgp_extensions` and
`delegations_reject_unused_undefined_openpgp_extensions` failed because the
metadata was accepted. The retained raw command and output have SHA-256
`e941e9e5d095d6ac2ed8ea00ade6eec208de739440bfaabcf040d8ecf334dbe4`
and `1b27e24a26a1cb253d67f610ab94db47fef77fcf80701d8ff7e601c0eaaeec46`.

The first green stage kept that exact test source and used corrected patch
`8540324f3cd231ca244928024b2b1eea92ec2e16433187b2e4b708696b8e50dc`.
The same targeted command passed both tests and exited 0. Its raw command and
output have SHA-256
`332baa7173f6f9fbb918a519e30a88282329aee699fe4c27af68bdd8dcc57ea3`
and `e359a68b01f841600a719e61899c7f8b39b4702d259aea8cd941c1a376910cb5`.

The final test source has SHA-256
`9b1b8e609feac0e12aa03cc442af57293e067b128edf012e9fb6bec6d9858f73`.
It retains both counterexamples, checks signer-used undefined fields at both
the direct-verification and ingestion boundaries, and adds a focused control
that existing Ed25519 outer and `keyval` extensions retain their prior parsing
behavior. The hash-preflighted, locked, offline integration command exited 0
with seven passing tests. Its raw command and output have SHA-256
`7c8df9ffab3e88f2811bdf16cceccf02e3861d209062151cccf235649611474c`
and `d96ee40684702ae8cc7ef9d05c6a3009d35c873cf8777ce814005bbb7d9cba4e`.
The randomized values below came from that same process:

```json
{"canonicalSignedBytes":36589,"compositeSigningKeyThresholdContributions":1,"conventionalKeyExtraFieldCompatibilityRetained":true,"delegatedDistinctTufIdsForOneCompositeSigningKeyRejected":true,"distinctTufIdsForOneCompositeSigningKeyRejected":true,"duplicateCompositeSignatureRejected":true,"ed25519ComponentCorruptionRejected":true,"hash":"SHA-512","issuerFingerprint":"1659B4550D8806B285A0A7084117744D52732C71E495B47162715935C004F406","keyId":"d68d01efdb88bb0f5755e3528bfd5ebb3f8c09cac8a3c2118522cc2a8e1649f6","keyType":"openpgp-rfc9580","mlDsa65ComponentCorruptionRejected":true,"outerReformatVerified":true,"publicKeyAlgorithm":30,"publicProjectionBytes":17935,"scheme":"openpgp-rfc9980-ml-dsa-65+ed25519-sha512","signaturePacketBytes":3464,"signaturePacketCount":1,"signatureType":0,"signatureVersion":6,"syntheticIndependence":"one generated composite key; no operator, custody, or underlying-key independence claim","thresholdIdentity":"verified-v6-openpgp-signing-key-fingerprint","thresholdTwoSatisfiedByOneCompositeKey":false,"undefinedOpenPgpExtensionsRejected":true,"unusedUndefinedOpenPgpKeysRejectedBeforeMetadataAcceptance":true,"verified":true}
```

An earlier final-integration bundle used the same semantics but formatted the
test source with the Rust 2024 mode. Its bytes and raw output remain retained,
but it is superseded by the Rust 2021 bundle above and is not completion
evidence for the final file.

## Patch and maintenance delta

The corrected 13,121-byte patch changes five upstream files with 209
insertions and 16 deletions. Relative to the reviewed 11,405-byte patch, it
adds two files to the patch surface, 20 insertions, one deletion, and 1,716
patch bytes:

- `schema::key::Key::validate_metadata_profile` owns the provisional profile
  check shared by parsing and direct signature verification.
- `schema::de::deserialize_keys` calls it for every key-map value before
  metadata construction.
- `schema::error::Error` gains an invalid-key profile error for the parsing
  path.

The Tough manifest dependency, both lockfiles, canonicalizer, accepted
certificate/signature profile, threshold identity, and Root/Delegations
verification loops are unchanged. The patch reproduces byte-for-byte from the
modified source and applies cleanly to pristine Tough commit
`98d8eb8b2ce63515d9b4981c938ef6453c5b5771`.

## Tough compatibility boundary at the Cycle 2 checkpoint

This section records the then-current blocked state. The preparation,
inspection, execution, and focused compatibility regression work has since
completed; its exact inputs and results are in the
[current compatibility record](current-compatibility.md).

Before attempting the upstream suite, the Tough manifest, lockfile, features,
and test targets were inspected. The default crate suite covers the library
and the discovered integration targets. The `http` and `http2` feature suites
are outside the prototype's enabled feature set; the `integ` feature also
requires a separately installed `noxious-server`, so those optional feature
sets are excluded.

The pinned Tough lockfile has SHA-256
`4614aae895dc084dc1abb34a13f3322f60456108a3abf529f52af246f6b5bfdb`.
The existing inspected cache still resolves the unchanged 189-package
prototype graph, but it cannot resolve Tough's normal/build/dev test graph.
The locked, offline graph command exited 101 before dependency or test code
ran because the crates.io index entry for `reqwest` was absent. The lock pins
the directly requested version to `reqwest` 0.13.4 with checksum
`219c5811de6525e5416c7d5d53bb656d3afdbc6c5af816e0802bcfa42dbdc1c3`.
That is the first missing resolver input, not a claim that it is the only new
package. The raw resolution command and output have SHA-256
`e4313a008c7932cad201c70b4aea24333b45a63967430686aab33bb17c5b661f`
and `0f4b7de8214e579f0b29eb7acfdf3b6047cbf1e138ae210610e0868d5fee16b2`.

Preparation must fetch the target-specific graph from this exact manifest and
lockfile into a disposable, credential-free cache without building it. The
resulting graph must then be diffed against the already inspected prototype
graph, and only newly selected manifests, build scripts, and proc macros must
be inspected before the default Tough suite is executed in the established
locked, offline boundary.

## Cycle 2 checkpoint verification and limits

- The full prototype `cargo test --locked --offline` run passed seven
  integration tests plus empty unit and doc-test targets. Its raw command and
  output hashes are
  `53cdfacd67262765d68eda62fd8cb1fb7b97316769f9fce986a46aaf51dc633d`
  and `68a0fd62a8e5fef9654d15c00101d76ceae6bedbb12a4300825050a76e8a68d7`.
- `cargo clippy --locked --offline --all-targets -- -D warnings` passed.
  Its raw command and output hashes are
  `b8218ea6de58eea8abd6d6dd800ac17b9801b21e0c1e59ee356b50fb3acc1fb7`
  and `8e4b3ebc85d38a5341a56d6d1d9ce1ea5af7c81907443e6174549088c8793edb`.
- Explicit Rustfmt checks for every task-authored Rust file passed.
- Prototype and patched-source `git diff --check` passed.
- A clean replay applied the patch to the pristine pinned Tough source and
  matched all five modified source files and the captured patch byte-for-byte.

At this checkpoint, the metadata-wide boundary was implemented and the pinned
Tough suite still needed the preparation and inspection above. That
compatibility work is now corrected pending independent review, as recorded in
the [current compatibility record](current-compatibility.md). Independent
review has not passed. All later all-role, clock, durable
refresh/root-rotation, held-byte policy, POUF, consumer, macOS, and
operator/custody work remains outside this slice.
