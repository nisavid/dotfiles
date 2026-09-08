# RFC 9980 first executable slice

The pinned Rust path signs and verifies canonical TUF root metadata with the provisional composite profile. The verifier rejects corruption of either signature component. This proves only the first publisher/verifier seam; issue #278 remains incomplete.

## Frozen inputs

- TUF specification: 1.0.36
- Tough commit: `98d8eb8b2ce63515d9b4981c938ef6453c5b5771`
- Tough tree: `2eb4bd2fc529460a9f0e021dae88861a3632e1a9`
- Sequoia commit: `0b0c8c7f038b829de2da0d28a822941d8600f3ee`
- Sequoia tree: `85b7646f4bbf4a323beb03b4ead52b4db6f9ab64`
- Rust and Cargo: 1.98.1
- OpenSSL: 3.6.3
- Target: `x86_64-unknown-linux-gnu`
- Prototype manifest SHA-256: `23861ca0bdef144e3974a753acac92ff715f53cd1614b16bf277488d4d737624`
- Final lock SHA-256: `02d9911a563dc2444f2252f8c47a31a545dec1c34fe0fa877ee8c11b0d879ad9`
- Lock package entries: 227

The pristine source repositories remained detached and clean. The final lock differs from the coordinator-prepared lock only because Tough now records its direct Sequoia dependency.

## Pre-execution inspection

The coordinator fetched dependencies without building them. Before the first build, I inspected the final selected graph and verified every selected registry archive against its lock checksum.

- Selected packages after the patch: 189
- Selected registry packages and verified archives: 184
- Selected path packages: 5
- Packages with custom build targets: 30
- Proc-macro packages: 16
- Selected-manifest inventory SHA-256: `a405b64cf88b869f55ff299bc8ef9f3392a890c96c0b759b499cfe563f204fe6`
- Build-script source inventory SHA-256: `fe4f7c7454b61b5608389b50e243bf8118d74fb56b537cbd47ad65e790302013`
- Proc-macro source inventory SHA-256: `f2d1b676aafc6857ab2fce85de0d20106397a26c3d3663f3bc543a0195e62b05`

The build-script review covered 30 entry points and their included modules: 50 Rust files and 16,025 lines, including modules compiled only under `cfg(test)`. No socket or network-client capability appeared. The executable actions invoke local Rust, C/C++, CMake, pkg-config, bindgen, LALRPOP, and linker tools and write generated data under Cargo's output directory.

The proc-macro review covered 233 Rust files and 37,825 lines. Targeted scans found no network, child-process, filesystem, FFI, or unsafe-code capability in those source trees.

The source findings from the preceding inspection remain unchanged:

- `SignedRole::new` signs Tough's canonical `signed` bytes through the public `Sign` hook.
- `Root::verify_role` canonicalizes the same object and dispatches through `Key::verify`.
- Tough counts each distinct authorized TUF key ID once toward a threshold.
- Sequoia maps algorithm 30 to `MLDSA65_Ed25519`; its OpenSSL backend accepts only when both component checks succeed.
- Sequoia's OpenSSL backend requires OpenSSL 3.5 or newer.

I found no material discrepancy with the reviewed feasibility report.

## Execution boundary

All build and test commands used an empty environment. They passed only the toolchain/system `PATH`, scratch `CARGO_HOME`, scratch `CARGO_TARGET_DIR`, `CARGO_TERM_COLOR=never`, and scratch `TMPDIR`; `HOME` and credentials remained unset.

Bubblewrap mounted the source and host root read-only, isolated user, PID, IPC, UTS, and cgroup namespaces, and made only the scratch Cargo home, target, and temporary directories writable. The host denied Bubblewrap's private-network setup with `NETLINK_ROUTE socket: Operation not permitted`. The executed boundary therefore shared the harness's already restricted network namespace. Cargo also ran with `--offline`, and the inspected build-script surface contained no network client.

The generated certificate and secret key material lived only in the test process. The fixture used no operator identity, production authority, custody service, credential, trust store, or persistent key file.

## Red

The first locked, offline test command exited 101 before any implementation patch. Rust reported:

```text
error[E0432]: unresolved imports tough::schema::key::OpenPgpKey,
              tough::schema::key::OpenPgpScheme
error[E0599]: no variant named OpenPgp found for enum tough::schema::key::Key
```

This was the intended public-seam failure.

## Patch

`patches/tough-openpgp-rfc9980.patch` changes only:

- `tough/Cargo.toml`
- `tough/src/schema/key.rs`

It adds the exact key type and scheme, parses one canonical unarmored public certificate and detached signature packet, requires v6/type 0/algorithm 30/SHA-512/one matching issuer, requires one policy-valid composite signing key, and accepts only Sequoia's `GoodChecksum`. The existing publisher hook, canonicalizer, threshold counter, and role verifier remain intact.

Patch SHA-256: `6c8563058fceb8aabe26ab0afb49297cc53d800c1104ebb4ea258aa47cc80c1c`. The patch matches the modified scratch source byte-for-byte and passes `git apply --check` against the pristine Tough commit.

## Green

The final locked, offline package test passed:

```text
test publisher_and_verifier_require_both_rfc9980_components ... ok
test result: ok. 1 passed; 0 failed
```

Its final observable record was:

```json
{"canonicalSignedBytes":36589,"compositeKeyCountsAsTufKeyIds":1,"duplicateCompositeSignatureRejected":true,"ed25519ComponentCorruptionRejected":true,"hash":"SHA-512","issuerFingerprint":"4AFA6C338FB671509BDAF3B753FC0A4D7B4F3D71E507C032343878D7B92EA7B5","keyId":"e1ffe459e1de452844b75b32bf9994a48fc0902d2edef5fbefba4624f543ac3a","keyType":"openpgp-rfc9580","mlDsa65ComponentCorruptionRejected":true,"outerReformatVerified":true,"publicKeyAlgorithm":30,"publicProjectionBytes":17935,"scheme":"openpgp-rfc9980-ml-dsa-65+ed25519-sha512","signaturePacketBytes":3464,"signaturePacketCount":1,"signatureType":0,"signatureVersion":6,"syntheticIndependence":"one generated composite key; no operator, custody, or underlying-key independence claim","thresholdTwoSatisfiedByOneCompositeKey":false,"verified":true}
```

The key ID and issuer fingerprint change on each run because the fixture generates a disposable key. The verdict and format assertions are stable.

Independent mutations of the serialized Ed25519 and ML-DSA-65 signature components both made `Root::verify_role` return an error. Duplicating the composite signature did not satisfy threshold 2 because Tough rejected the repeated key ID. Compact outer JSON reparsed and verified because the signature binds the canonical `signed` object.

## Final checks

- `cargo test --locked --offline`: passed, including the integration test and doc-test target
- `cargo clippy --locked --offline --all-targets -- -D warnings`: passed
- Explicit Rustfmt checks for the prototype and patched Tough source: passed
- `git diff --check` for the prototype and patched Tough source: passed
- Frozen patch comparison and pristine-source `git apply --check`: passed

`cargo fmt --all -- --check` traversed the pristine Sequoia workspace and reported its existing style differences under Rustfmt 1.98.1. It changed no files. The explicit checks above cover every task-authored Rust file.

## Limits and next slice

This Linux result does not qualify macOS. It does not cover targets, snapshot, timestamp, delegated targets, root rotation, durable refresh/crash recovery, caller-supplied accepted time, target confinement, metadata limits, held-byte policy composition, or the POUF draft.

The next bounded slice should protect root, targets, snapshot, timestamp, and one delegated targets role with this same key/signature seam. Root rotation and durable state-transition work should remain a later slice.
