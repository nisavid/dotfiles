# RFC 9980 prototype source and build inspection

The first executable slice signs and verifies canonical TUF root metadata with
the provisional OpenPGP v6 algorithm-30 composite profile. This document records
the source and build boundary inspected before fetched code ran. See the
[current threshold-identity record](slice-5-threshold-identity.md) for revised
test sequencing, observable output, and final checks. The
[original red/green record](slice-3-red-green.md) is preserved as historical
evidence for the candidate that independent review later rejected.

## Pinned boundary

- Repository base: `42d8f2595e362b036161ff0030297bcb54fa7fcb`
- TUF specification: 1.0.36
- [Tough](https://github.com/awslabs/tough) commit:
  `98d8eb8b2ce63515d9b4981c938ef6453c5b5771`; tree
  `2eb4bd2fc529460a9f0e021dae88861a3632e1a9`
- [Sequoia](https://gitlab.com/sequoia-pgp/sequoia) commit:
  `0b0c8c7f038b829de2da0d28a822941d8600f3ee`; tree
  `85b7646f4bbf4a323beb03b4ead52b4db6f9ab64`
- Rust and Cargo: 1.98.1
- Observed OpenSSL: 3.6.3; required external OpenSSL: 3.5 or newer
- Observed target: `x86_64-unknown-linux-gnu`; macOS was not executed
- Prototype manifest SHA-256:
  `23861ca0bdef144e3974a753acac92ff715f53cd1614b16bf277488d4d737624`
- Final lock SHA-256:
  `02d9911a563dc2444f2252f8c47a31a545dec1c34fe0fa877ee8c11b0d879ad9`
- Lock package entries: 227
- Tough patch SHA-256:
  `e2070c8deba02f51c9c47e2bf868da52cd761847a6e0ba6ed7b9bfdad737e42e`
- Final integration-test SHA-256:
  `9057b159657ebc7113d729b87cf405fc2474fa55e51211bfdf2b0184cbc5965f`

The manifest resolves Tough from `.scratch/tough/tough` and Sequoia OpenPGP from
`.scratch/sequoia/openpgp`. The complete Tough and Sequoia workspaces also supply
the nested `olpc-cjson` and `buffered-reader` path dependencies. The pinned
pristine source trees remained detached and clean.

## Selected dependency graph

Dependencies were fetched without building them. The final target-filtered,
locked graph contained:

- 189 selected packages
- 184 crates.io registry packages
- Five path packages: this prototype, Tough, `olpc-cjson`, Sequoia OpenPGP, and
  `buffered-reader`
- 30 packages with custom-build targets
- 16 proc-macro packages

All 184 selected registry archives matched the SHA-256 checksums in
`Cargo.lock`. The reviewed inventories were:

- Selected manifests:
  `a405b64cf88b869f55ff299bc8ef9f3392a890c96c0b759b499cfe563f204fe6`
- Build-script source:
  `fe4f7c7454b61b5608389b50e243bf8118d74fb56b537cbd47ad65e790302013`
- Proc-macro source:
  `f2d1b676aafc6857ab2fce85de0d20106397a26c3d3663f3bc543a0195e62b05`

The build-script review followed 30 entry points through included modules: 50
Rust files and 16,025 lines, including modules compiled only under `cfg(test)`.
No socket or network-client capability appeared. The observed executable actions
invoke local Rust, C/C++, CMake, `pkg-config`, bindgen, LALRPOP, and linker tools
and write generated files under Cargo's build output directory.

The proc-macro review covered 233 Rust files and 37,825 lines. Targeted scans
found no network, child-process, filesystem, FFI, or unsafe-code capability in
those source trees. These targeted scans and manual reviews support this bounded
execution decision; they are not a full dependency or security audit.

## Source findings

- `SignedRole::new` signs Tough's canonical `signed` bytes through the public
  `Sign` hook.
- `Root::verify_role` canonicalizes the same object and dispatches through
  `Key::verify`.
- Unpatched Tough rejects a repeated identical key ID and counts each distinct
  authorized TUF key ID once toward its threshold in both root and delegation
  verification.
- The unpatched `Key` enum had no composite OpenPGP verifier branch.
- Sequoia maps algorithm 30 to `MLDSA65_Ed25519`; its OpenSSL backend accepts a
  composite signature only when both component checks succeed.
- Sequoia's OpenSSL backend enables algorithm 30 only with external OpenSSL 3.5
  or newer. Sequoia OpenPGP is LGPL-2.0-or-later.

No material discrepancy with the reviewed feasibility report was found.

Independent review of the frozen slice later found the valid P1
`RR1-THRESHOLD-IDENTITY-001`. The OpenPGP verifier ignored flattened extra key
fields, but Tough serialized those fields when deriving the TUF key ID. The same
certificate could therefore be encoded as two key objects with different valid
IDs, and the same detached signature could be relabeled under both IDs to
satisfy threshold 2.

The revised patch keeps TUF-key-ID threshold identity for existing key types.
For this provisional OpenPGP profile, successful verification returns the
verified v6 signing-key fingerprint as a domain-separated threshold identity.
The existing root and delegation loops count that identity once, regardless of
how many authorized TUF key IDs project the same signing key. Nonempty flattened
fields on the OpenPGP key or its `keyval` make that key ineligible to verify.
This changes no dependency, accepted profile, canonicalization rule, publisher
hook, or TUF update-state path.

## Execution boundary

Build and test commands started with an empty environment and passed only the
toolchain/system path, disposable Cargo and target directories, deterministic
terminal-color configuration, and a disposable temporary directory. No
credentials or production material entered the boundary. Source and host files
were read-only; only those three disposable directories were writable. Cargo ran
with `--locked --offline`.

The host denied Bubblewrap's private-network setup with `NETLINK_ROUTE socket:
Operation not permitted`. The observed execution therefore shared the parent
harness's already restricted network namespace while retaining user, PID, IPC,
UTS, and cgroup isolation. Cargo's offline mode and the inspected build-script
surface reduced exposure but did not create the network boundary. A portable
replay must either create its own private network namespace or run inside a
separately verified network-denied parent sandbox.

The test generated its certificate and secret key only in process. It used no
operator identity, production authority, custody service, credential, trust
store, or persistent key file.

## Result boundary

The final locked test preserves the root-metadata publisher/verifier result:
compact and reformatted outer JSON verified, corruption of either composite
component failed verification, and a repeated identical key ID could not
satisfy threshold 2. It also rejects undefined OpenPGP fields and prevents two
correctly derived TUF key IDs for one verified composite signing-key fingerprint
from satisfying threshold 2 through either root or delegation verification.
This is the implementation disposition for the P1; a new independent review has
not yet adjudicated the revised candidate.

This Linux observation does not qualify macOS or the remaining TUF roles. It
does not cover root rotation, durable refresh/crash recovery, caller-supplied
accepted time, target confinement, metadata limits, held-byte policy
composition, the POUF draft, or operator/custody independence.
