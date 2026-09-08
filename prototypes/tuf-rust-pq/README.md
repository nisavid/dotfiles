# RFC 9980 TUF Rust prototype

This throwaway prototype signs and verifies canonical TUF root metadata with one
OpenPGP v6 algorithm-30 composite signature. The tested verifier rejects damage
to either the Ed25519 or ML-DSA-65 component. Across root and delegated-targets
verification, one verified composite signing-key fingerprint contributes at
most once to a signature threshold even when authorized key objects have
different correctly derived TUF key IDs. Undefined fields on the provisional
OpenPGP key object or its `keyval` are rejected during verification.

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

The result was observed only on `x86_64-unknown-linux-gnu` with Rust and Cargo
1.98.1 and external OpenSSL 3.6.3. The Sequoia backend requires external OpenSSL
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

Verify the prototype inputs, apply the sole Tough patch, and verify its output:

```sh
sha256sum -c <<'CHECKSUMS'
23861ca0bdef144e3974a753acac92ff715f53cd1614b16bf277488d4d737624  Cargo.toml
02d9911a563dc2444f2252f8c47a31a545dec1c34fe0fa877ee8c11b0d879ad9  Cargo.lock
e2070c8deba02f51c9c47e2bf868da52cd761847a6e0ba6ed7b9bfdad737e42e  patches/tough-openpgp-rfc9980.patch
9057b159657ebc7113d729b87cf405fc2474fa55e51211bfdf2b0184cbc5965f  tests/composite_metadata.rs
CHECKSUMS

git -C .scratch/tough apply --check \
  ../../patches/tough-openpgp-rfc9980.patch
git -C .scratch/tough apply ../../patches/tough-openpgp-rfc9980.patch

sha256sum -c <<'CHECKSUMS'
8b4c3d4803ed2e0fa4250fd7e9069b628d537b67122f999e6ae78a35118cbb84  .scratch/tough/tough/Cargo.toml
0475738e80b34934af6ae8f277693f3b4437283f952514d5b3a40796b4532488  .scratch/tough/tough/src/schema/key.rs
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

The test should report four passing integration tests. Its generated key ID and
fingerprint vary by run. Compare the stable format and rejection assertions with
the [current threshold-identity execution record](evidence/slice-5-threshold-identity.md).
The [original red/green record](evidence/slice-3-red-green.md) is historical and
describes the independently reviewed candidate before the correction.

## Scope

This slice covers the root publisher/verifier seam and the composite
threshold-identity boundary in root and delegation verification. The delegation
test is a direct `Delegations::verify_role` seam, not an all-role repository
qualification. The slice does not qualify targets, snapshot, timestamp, full
delegated-targets behavior, root rotation, durable refresh or crash recovery,
caller-supplied accepted time, target confinement, metadata limits, held-byte
policy composition, the POUF draft, or any operator/custody independence claim.
