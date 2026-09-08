# RFC 9980 TUF Rust prototype

This throwaway prototype signs and verifies canonical TUF root metadata with one
OpenPGP v6 algorithm-30 composite signature. The tested verifier rejects damage
to either the Ed25519 or ML-DSA-65 component. Across root and delegated-targets
verification, one verified composite signing-key fingerprint contributes at
most once to a signature threshold even when authorized key objects have
different correctly derived TUF key IDs. Undefined fields on the provisional
OpenPGP key object or its `keyval` are rejected before Root or Delegations
metadata is accepted, including when the key is unused. Direct verification of
programmatically constructed keys applies the same check.

> [!CAUTION]
> This is one synthetic publisher/verifier seam, not a production security
> design. Use a disposable, credential-free environment and no production key
> material, identities, trust stores, or metadata.

Independent review found `RR1-THRESHOLD-IDENTITY-001` in the historical frozen
slice: Tough counted successful verifications by distinct TUF key ID, while the
OpenPGP verifier ignored fields that changed that ID. The revised patch returns
a domain-separated threshold identity from signature verification. Existing key
types retain TUF-key-ID identity; this provisional OpenPGP profile uses the
verified v6 signing-key fingerprint. Root and delegation verifiers count each
identity once. This is the proposed correction, pending a new independent
review; it is not an operator, custody, or underlying-component independence
claim.

A second independent review found that the undefined-field check still ran
only for a key selected to verify a signature. The current patch moves that
profile validation to the shared metadata key-map deserializer and retains it
in direct verification. The correction has new reproducible red/green
evidence. The applicable pinned Tough default suite now passes, and two focused
ECDSA regressions exercise the conventional `Key::verify` identity through
both public threshold loops. This compatibility correction still awaits
independent review; see the
[current compatibility record](evidence/current-compatibility.md).

The current prototype and Tough results were observed on
`x86_64-unknown-linux-gnu` with Rust and Cargo 1.98.1 and external OpenSSL
3.6.3. An earlier Tough run used the host's Rust and Cargo 1.98.0 and remains
only as superseded diagnostic evidence. The Sequoia backend requires OpenSSL
3.5 or newer. macOS remains unexecuted.

## Prerequisites

- Git and GNU `sha256sum`
- Rust and Cargo 1.98.1
- OpenSSL 3.5 or newer, including headers and `pkg-config` metadata
- A C/C++ toolchain, CMake, `pkg-config`, and libclang for the inspected native
  build surface
- Bubblewrap, or an equivalent sandbox that can make the source read-only,
  expose only scratch build directories as writable, and deny network access
- Public network access for the source and locked-crate fetch only

Run the following commands from this directory.

## Reconstruct the pinned sources

The root manifest has two source-tree dependencies under `.scratch/`: Tough at
`.scratch/tough/tough` and Sequoia at `.scratch/sequoia/openpgp`. Cloning both
complete workspaces also supplies Tough's `olpc-cjson` and Sequoia's
`buffered-reader` path dependencies.

```sh
set -eu

tuf278_tough_commit=98d8eb8b2ce63515d9b4981c938ef6453c5b5771
tuf278_tough_tree=2eb4bd2fc529460a9f0e021dae88861a3632e1a9
tuf278_sequoia_commit=0b0c8c7f038b829de2da0d28a822941d8600f3ee
tuf278_sequoia_tree=85b7646f4bbf4a323beb03b4ead52b4db6f9ab64

test ! -e .scratch/tough
test ! -e .scratch/sequoia
mkdir -p .scratch

git init -q .scratch/tough
git -C .scratch/tough remote add origin https://github.com/awslabs/tough.git
git -C .scratch/tough -c core.hooksPath=/dev/null fetch \
  --depth=1 --no-tags origin "$tuf278_tough_commit"
git -C .scratch/tough -c core.hooksPath=/dev/null checkout \
  --quiet --detach FETCH_HEAD

git init -q .scratch/sequoia
git -C .scratch/sequoia remote add origin \
  https://gitlab.com/sequoia-pgp/sequoia.git
git -C .scratch/sequoia -c core.hooksPath=/dev/null fetch \
  --depth=1 --no-tags origin "$tuf278_sequoia_commit"
git -C .scratch/sequoia -c core.hooksPath=/dev/null checkout \
  --quiet --detach FETCH_HEAD

test "$(git -C .scratch/tough rev-parse HEAD)" = "$tuf278_tough_commit"
test "$(git -C .scratch/tough rev-parse 'HEAD^{tree}')" = "$tuf278_tough_tree"
test "$(git -C .scratch/sequoia rev-parse HEAD)" = "$tuf278_sequoia_commit"
test "$(git -C .scratch/sequoia rev-parse 'HEAD^{tree}')" = \
  "$tuf278_sequoia_tree"
```

Verify the prototype inputs, apply the main Tough source patch, and verify its
output:

```sh
sha256sum -c <<'CHECKSUMS'
23861ca0bdef144e3974a753acac92ff715f53cd1614b16bf277488d4d737624  Cargo.toml
02d9911a563dc2444f2252f8c47a31a545dec1c34fe0fa877ee8c11b0d879ad9  Cargo.lock
8540324f3cd231ca244928024b2b1eea92ec2e16433187b2e4b708696b8e50dc  patches/tough-openpgp-rfc9980.patch
8720ad3dd63c05109761b624922248b94a938205a1d43987032d93e73377100c  patches/tough-default-sequoia-source.patch
8951066c56b6f1fbbc391aedcdf6e15322f88356ff0f2d4d04b3ebf926fbe268  evidence/tough-default.Cargo.lock
c2ab4935f0c58ca4a1ad398007b2ba7c8e9e0c81ed7ea70368e00e4c933f3724  tests/composite_metadata.rs
CHECKSUMS

git -C .scratch/tough apply --check \
  ../../patches/tough-openpgp-rfc9980.patch
git -C .scratch/tough apply ../../patches/tough-openpgp-rfc9980.patch

sha256sum -c <<'CHECKSUMS'
8b4c3d4803ed2e0fa4250fd7e9069b628d537b67122f999e6ae78a35118cbb84  .scratch/tough/tough/Cargo.toml
ac1b3c4fb6242f109a08bce5d10fcf8b2bbb56248a8b57c14792fc498dbb0575  .scratch/tough/tough/src/schema/de.rs
3ac428c534fa2b7560febb58b959091015ab20f84b2ba04170c71193d8094993  .scratch/tough/tough/src/schema/error.rs
0b62446332794800c3b24660acceb0d22a9e9f603ec69ae79a59ddf143879104  .scratch/tough/tough/src/schema/key.rs
dc9d19ecf6332fa909b20e31d68463f0c64c79f54f8561bb0b8eeb0e714c6685  .scratch/tough/tough/src/schema/verify.rs
CHECKSUMS
```

## Fetch and inspect without executing dependencies

Create disposable Cargo, target, and temporary directories. `cargo fetch
--locked` may contact crates.io but cannot update `Cargo.lock`; the target flag
limits retrieval to the observed Linux graph.

```sh
tuf278_root="$(pwd -P)"
tuf278_run="$(mktemp -d)"
tuf278_cargo="$(rustup which --toolchain 1.98.1 cargo)"
tuf278_toolchain_bin="$(dirname "$tuf278_cargo")"
mkdir -p "$tuf278_run/cargo-home" "$tuf278_run/target" "$tuf278_run/tmp"

env -i \
  PATH="$tuf278_toolchain_bin:/usr/bin:/bin" \
  CARGO_HOME="$tuf278_run/cargo-home" \
  CARGO_TERM_COLOR=never \
  "$tuf278_cargo" fetch --locked --target x86_64-unknown-linux-gnu

env -i \
  PATH="$tuf278_toolchain_bin:/usr/bin:/bin" \
  CARGO_HOME="$tuf278_run/cargo-home" \
  CARGO_TERM_COLOR=never \
  "$tuf278_cargo" metadata --locked --offline \
  --filter-platform x86_64-unknown-linux-gnu --format-version 1 \
  >"$tuf278_run/metadata.json"
```

Before executing fetched code, use the metadata and `Cargo.lock` to complete the
same bounded inspection:

1. Account for 189 selected packages: 184 registry packages and five path
   packages.
2. Verify all 184 selected registry archives against their lockfile SHA-256
   checksums.
3. Read every selected manifest. Inspect the entry point and included modules
   for all 30 custom-build packages, then inspect all 16 proc-macro source trees.
4. Confirm the build scripts invoke only the expected local Rust, C/C++, CMake,
   `pkg-config`, bindgen, LALRPOP, and linker tools, with generated output under
   Cargo's build directory.

The recorded review used targeted capability scans plus manual source reading;
it was not a full security audit. Its inventory digests and source findings are
in [the source/build inspection](evidence/source-build-inspection.md).

That 189-package inventory covers the prototype command below. The applicable
Tough normal/build/dev graph was separately resolved with the pinned Sequoia
path source. Of its 263 reachable packages, 145 package name/version pairs were
new relative to the prototype inventory. Their registry archives, manifests,
build scripts, and proc macros were inspected before the locked offline suite
ran. The exact graph, lock, results, and limits are in the
[current compatibility record](evidence/current-compatibility.md).

## Run the tested slice

First confirm that Bubblewrap can create a private network namespace:

```sh
bwrap --ro-bind / / --dev /dev --proc /proc --unshare-net \
  --die-with-parent --new-session /usr/bin/true
```

If that probe succeeds, the following command gives the source a read-only view
of the host, makes only the three disposable directories writable, starts with
an empty environment, and runs Cargo from the pre-fetched cache without network
access:

```sh
bwrap --ro-bind / / --dev /dev --proc /proc --unshare-all \
  --bind "$tuf278_run/cargo-home" "$tuf278_run/cargo-home" \
  --bind "$tuf278_run/target" "$tuf278_run/target" \
  --bind "$tuf278_run/tmp" "$tuf278_run/tmp" \
  --chdir "$tuf278_root" --die-with-parent --new-session \
  env -i \
    PATH="$tuf278_toolchain_bin:/usr/bin:/bin" \
    CARGO_HOME="$tuf278_run/cargo-home" \
    CARGO_TARGET_DIR="$tuf278_run/target" \
    CARGO_TERM_COLOR=never \
    TMPDIR="$tuf278_run/tmp" \
    "$tuf278_cargo" test --locked --offline \
      --test composite_metadata -- --nocapture
```

On the reviewed host, the private-network probe failed before code ran because
the host denied Bubblewrap's `NETLINK_ROUTE` socket. The recorded green run used
`--unshare-all --share-net` only inside a parent harness that already denied
network access. Use that substitution only after independently verifying the
parent network denial; otherwise the replay prerequisite is unsatisfied.

The test should report nine passing integration tests: the seven existing
composite and profile-boundary tests plus two focused conventional ECDSA tests.
Its generated key ID and fingerprint vary by run. Compare the stable format and
rejection assertions with the
[current compatibility record](evidence/current-compatibility.md). The
[Cycle 2 record](evidence/slice-8-cycle-2.md),
[threshold-identity record](evidence/slice-5-threshold-identity.md), and
[original red/green record](evidence/slice-3-red-green.md) preserve their
historical checkpoints.

## Run the applicable Tough suite

The patched Sequoia edge needs a workspace source override and its ordinary
Cargo-resolved test lock; the pristine upstream lock is not the executed lock.
After applying the main source patch above, apply the replay inputs:

```sh
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

Fetch the locked Linux test graph without building it. Before execution,
repeat the bounded graph-delta inspection in the current compatibility record.

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

Then use the same empty-environment, read-only-source, offline sandbox and run
the following direct Cargo invocation. Resolve the binary path before entering
the empty environment so the command does not depend on a rustup shim or home
configuration.

```sh
tuf278_tough_cargo="$(rustup which --toolchain 1.98.1 cargo)"
"$tuf278_tough_cargo" test --locked --offline \
  --manifest-path .scratch/tough/tough/Cargo.toml \
  --package tough \
  --target x86_64-unknown-linux-gnu \
  --no-default-features
```

The recorded run passed 78 tests, failed 0, and ignored 1. No Tough feature was
enabled; `http`, `http2`, and `integ` remain outside this slice. The current
compatibility record binds the exact command and outputs by SHA-256.

## Scope

This slice covers the root publisher/verifier seam and the composite
threshold-identity boundary in root and delegation verification. The delegation
test is a direct `Delegations::verify_role` seam, not an all-role repository
qualification. The slice does not qualify targets, snapshot, timestamp, full
delegated-targets behavior, root rotation, durable refresh or crash recovery,
caller-supplied accepted time, target confinement, metadata limits, held-byte
policy composition, the POUF draft, or any operator/custody independence claim.
