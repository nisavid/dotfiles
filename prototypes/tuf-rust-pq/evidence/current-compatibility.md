# Current Tough compatibility evidence

`RR2-SHARED-VERIFY-COMPATIBILITY-EVIDENCE-001` is corrected pending
independent review. The applicable Tough default suite passed on the pinned
patched source, and two focused prototype tests now cover the conventional
ECDSA verification path that suite does not exercise. This is compatibility
evidence for the first-slice change, not a conventional-cryptography
qualification or completion of issue 278.

## Exact inputs

- Tough commit `98d8eb8b2ce63515d9b4981c938ef6453c5b5771`, tree
  `2eb4bd2fc529460a9f0e021dae88861a3632e1a9`
- Sequoia commit `0b0c8c7f038b829de2da0d28a822941d8600f3ee`, tree
  `85b7646f4bbf4a323beb03b4ead52b4db6f9ab64`
- Tough source patch SHA-256
  `8540324f3cd231ca244928024b2b1eea92ec2e16433187b2e4b708696b8e50dc`
- Tough test-workspace source override SHA-256
  `8720ad3dd63c05109761b624922248b94a938205a1d43987032d93e73377100c`
- Executed Tough test-workspace manifest SHA-256
  `93b0bc5e23558e9bc5475b05695a2359884bfa61a062f409bd1b9c25614fd2dc`
- Replay-layout Tough workspace manifest SHA-256
  `dd5807256002ffa16dfa4eba7c7db03ee3ba7daed2a74a9099b3496eda2314ba`
- Stored ordinary Cargo-resolved Tough test lock SHA-256
  `8951066c56b6f1fbbc391aedcdf6e15322f88356ff0f2d4d04b3ebf926fbe268`
- Patched Tough crate manifest SHA-256
  `8b4c3d4803ed2e0fa4250fd7e9069b628d537b67122f999e6ae78a35118cbb84`
- Current focused-test source SHA-256
  `c2ab4935f0c58ca4a1ad398007b2ba7c8e9e0c81ed7ea70368e00e4c933f3724`

The pristine upstream Tough lock has SHA-256
`4614aae895dc084dc1abb34a13f3322f60456108a3abf529f52af246f6b5bfdb`.
It is not the executed test lock: selecting the pinned Sequoia checkout by a
Cargo path override requires ordinary resolution. The stored lock above is the
result used by the passing suite. It contains no source checkout, cache, or
host path.

The executed and replay-layout workspace manifests differ only in the relative
path from the disposable Tough checkout to the same pinned Sequoia checkout.
An offline locked `cargo tree` replay selected Sequoia 2.4.1 from that checkout
and Tough 0.24.0 from the patched checkout.

## Results and coverage

The prototype has nine integration tests: the seven existing composite and
profile-boundary tests plus these two focused conventional-key tests:

- `root_retains_conventional_ecdsa_tuf_id_threshold_identity`
- `delegations_retain_conventional_ecdsa_tuf_id_threshold_identity`

Each test serializes and reparses an accepted key map containing two ECDSA key
objects with the same public key and distinct correctly derived TUF key IDs.
Two valid signatures, one under each authorized ID, satisfy threshold 2. One
signature does not, and repeating an exact signature key ID is rejected. This
locks the existing conventional behavior of returning the authorized TUF key
ID from `Key::verify`; it makes no claim that the two key objects represent
independent signing keys.

The focused run passed both new tests; its command/output SHA-256 values are
`6b17e5f0227ee6e6d74ee11fc0a0cc858bebe1bc67818ee568c5755c1826fcec`
and `7836dde79f86e8e03b76c29b3ff4d23d392a68a8eac9717a0656e435ce37e4f3`.
The full prototype run passed all 9 tests. Its command/output SHA-256 values are
`d94b2cd81ab9d24ee8f1de0bdecdc523875666a462e1fa15848990c3366bb915`
and `cfb0507862239fc091d4a36989aafa8ccf3761cf65ecc62cbbe2fc9767805940`.
Clippy with all targets and warnings denied also passed; its command/output
SHA-256 values are
`572a1e0c147cb74420e84531abcfcd3875860802f31d89999fe8759306f7e53d`
and `38a93aafab9e9b62498013cf8cab9bc6665b441191c7b1b4d10aee06ccb7059e`.
These current prototype runs used Rust and Cargo 1.98.1.

The exact-toolchain Tough run passed 78 tests, failed 0, and ignored 1. Its
command/output SHA-256 values are
`2904bc139ea944a3a59341b68fc2899aa31820c987808b6ebd5af948d57833d6`
and `995301fdff04d3c578fa6ba4ba58337d3b79da588885ec39b7e92be6349eb4d7`.
The command invoked Cargo, rustc, and rustdoc through explicit 1.98.1 paths;
their binary SHA-256 values are
`da77c8b33849312255ccde3179198ada4c8deb370488d050286146b1d1b27e14`,
`859254978c0a0402c32f949f6de0d99aee73be8d15f45aac00ae1448aac51e74`,
and `3ff7fed6d1064d8d75d24ae8beff9fe1d68031d3d819966481d22c3c9002b709`.
The retained output reports Cargo 1.98.1, rustc 1.98.1, rustdoc 1.98.1, and
OpenSSL 3.6.3 on `x86_64-unknown-linux-gnu`. The run enabled no Tough features.
The `http`, `http2`, and `integ` feature suites were excluded; no HTTP test ran,
and the separately installed `noxious-server` integration surface was not
used.

The earlier Rust and Cargo 1.98.0 run also passed 78 tests. Its command, first
full output, and latest verification-output SHA-256 values are
`43afd683959bc5cdeae6bcdce5b0cf3729ed0c810947da3949a82037bf3e4057`,
`64cc71590b23bacc59be7a403c5c7fe62c0c2bc5a907d7ceeb2938713e178808`,
and `ba0c1788ef2c536a9dad2ce57dab274b112dc30b0997b96161c40f2b49e2e978`.
Those files remain superseded toolchain diagnostics, not exact-contract
compatibility evidence.

The default suite verifies RSA signatures and reference-repository Ed25519
signatures and ingests three ECDSA metadata encodings. It has no ECDSA
signature-verification test. The two focused tests close only that changed
identity-path gap through public `Root::verify_role` and
`Delegations::verify_role` seams. They do not expand the accepted parsing
boundary or qualify other conventional algorithms and encodings.

## Replay

After reconstructing the pinned checkouts and applying the main source patch
as described in the README, verify and apply the test-workspace inputs:

```sh
sha256sum -c <<'CHECKSUMS'
8720ad3dd63c05109761b624922248b94a938205a1d43987032d93e73377100c  patches/tough-default-sequoia-source.patch
8951066c56b6f1fbbc391aedcdf6e15322f88356ff0f2d4d04b3ebf926fbe268  evidence/tough-default.Cargo.lock
CHECKSUMS

git -C .scratch/tough apply --check \
  ../../patches/tough-default-sequoia-source.patch
git -C .scratch/tough apply \
  ../../patches/tough-default-sequoia-source.patch
cp evidence/tough-default.Cargo.lock .scratch/tough/Cargo.lock
sha256sum -c <<'CHECKSUMS'
dd5807256002ffa16dfa4eba7c7db03ee3ba7daed2a74a9099b3496eda2314ba  .scratch/tough/Cargo.toml
8951066c56b6f1fbbc391aedcdf6e15322f88356ff0f2d4d04b3ebf926fbe268  .scratch/tough/Cargo.lock
CHECKSUMS
```

Fetch the locked target graph without building it, then repeat the bounded
delta inspection described below before executing dependency code:

```sh
tuf278_tough_cargo="$(rustup which --toolchain 1.98.1 cargo)"
tuf278_tough_toolchain_bin="$(dirname "$tuf278_tough_cargo")"
env -i \
  PATH="$tuf278_tough_toolchain_bin:/usr/bin:/bin" \
  CARGO_HOME="$tuf278_run/cargo-home" \
  CARGO_TERM_COLOR=never \
  "$tuf278_tough_cargo" fetch --locked \
    --manifest-path .scratch/tough/tough/Cargo.toml \
    --target x86_64-unknown-linux-gnu
```

Use the README's empty-environment, read-only-source, offline sandbox for the
suite. Replace its Cargo invocation with the following command to replay the
observed Tough feature profile:

```sh
tuf278_tough_cargo="$(rustup which --toolchain 1.98.1 cargo)"
"$tuf278_tough_cargo" test --locked --offline \
  --manifest-path .scratch/tough/tough/Cargo.toml \
  --package tough \
  --target x86_64-unknown-linux-gnu \
  --no-default-features
```

The source/build inspection remains bounded: 145 package name/version pairs
were newly selected relative to the already inspected prototype graph; all 144
new registry archives matched their lock checksums, and the new manifest,
build-script, and proc-macro surfaces were inspected before execution. See the
[source/build inspection](source-build-inspection.md) and the historical
[Cycle 2 record](slice-8-cycle-2.md) for the retained limits and provenance.
