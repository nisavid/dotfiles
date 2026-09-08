# Rust and post-quantum TUF feasibility

## Decision

A bounded sequence of disposable feasibility prototypes is warranted. First
prove the Rust and post-quantum TUF integration, then exercise its transport and
representative consumer boundary. No inspected Rust TUF stack supports
Codiquary's RFC 9580/9980 profile off the shelf, but the missing work is
concentrated enough to test without implementing a new update protocol.

The preferred candidate is a version-pinned patch of [`tough` 0.24.0 at
`98d8eb8b2ce63515d9b4981c938ef6453c5b5771`](https://github.com/awslabs/tough/releases/tag/tough-v0.24.0),
using [`sequoia-openpgp` 2.4.1 at
`0b0c8c7f038b829de2da0d28a822941d8600f3ee`](https://gitlab.com/sequoia-pgp/sequoia/-/tags/openpgp%2Fv2.4.1)
for RFC 9980 signatures. `tough` already places a Rust client, repository editor,
and publisher CLI around one metadata model. Sequoia 2.4.1 already implements
RFC 9980 through its OpenSSL and RustCrypto backends. The first prototype must add
and exercise the connection between those two existing implementations; it must
not replace either cryptographic construction or TUF's update workflow.

This is a positive prototype decision, not a TUF adoption decision. Adoption
remains conditional on a supportable upstream change or consciously owned patch,
a versioned POUF, preserved Codiquary policy, clean conformance evidence, and a
representative nonprivileged consumer integration on the final candidate.

## What exists and what is missing

The assessment is bound to the public versions and revisions named below as of
2026-09-08.

| Surface | Existing support | Required Codiquary work | Classification |
| --- | --- | --- | --- |
| TUF client workflow | `tough` loads sequential roots, timestamp, snapshot, targets, and recursively fetched delegated roles; it enforces thresholds, expiry, rollback checks, length limits, and target paths. | Preserve the specified stepwise root and refresh transitions, including durable intermediate-root, timestamp, and snapshot state, while exposing an accepted trusted-time input. Hold verified target payload bytes outside application state until retained Codiquary policy accepts them, and test this split against the accepted atomic client-state contract. | Bounded upstream change or downstream patch plus adoption-time contract mapping. |
| Repository publisher | `RepositoryEditor`, `TargetsEditor`, and `SignedRole` build and sign all roles. `SignedRole` signs the OLPC canonical-JSON bytes through a `Sign` implementation. `tuftool` 0.17.0 is the stock CLI. | Add an RFC 9980 key representation and a programmatic OpenPGP `KeySource`/`Sign` implementation. Keep production secret custody behind the separate operator boundary; do not teach the stock CLI to read unprotected production keys. | Documented signing hook plus a required schema patch. |
| Client signature verification | `Root::verify_role` and delegation verification dispatch through the concrete `schema::key::Key` verifier. The public key enum has RSA, Ed25519, and ECDSA variants. `RepositoryLoader` has no verifier-provider parameter. | Add one OpenPGP key variant and strict Sequoia verification of the complete detached signature. A publisher-only `Sign` implementation is insufficient. | Required patch; no existing extension point. |
| RFC 9980 primitive and packets | Sequoia 2.4.1 adds ML-DSA-65+Ed25519 key generation, signature parsing, signing, verification, and policy identifiers. Its OpenSSL and RustCrypto backends support the RFC 9980 algorithms. | Pin one backend and qualify it. Prefer the backend Sequoia marks production-ready and constant-time for any code that handles signing secrets; keep the RustCrypto path disposable until separately qualified. | Existing implementation, qualification required. |
| Canonical TUF metadata | Publisher and verifier use `olpc_cjson::CanonicalFormatter` over the `signed` role. The serialized outer metadata may be pretty-printed without changing the signed bytes. | Freeze this exact form in the POUF and add differential fixtures. Keep Codiquary's JCS objects as distinct target objects; one object version must never accept both canonical forms. | Existing support plus profile and tests. |
| Key identity and thresholds | TUF 1.0.36 defines a SHA-256 key ID over the canonical key object and counts distinct authorized key IDs toward a positive role threshold. `tough` follows that model. | Keep the TUF key ID distinct from the RFC 9580 v6 fingerprint. Treat one RFC 9980 composite key as one TUF threshold key; its Ed25519 and ML-DSA components are not two quorum votes. | POUF mapping, no threshold-algorithm change. |
| SHA-512 binding | The accepted Codiquary objects use SHA-512. `tough`'s editor and schema paths inspected here produce or require SHA-256 references. | Require SHA-512 alongside any compatibility SHA-256 reference and verify it for targets and metadata under this POUF. The retained Codiquary policy gate must still verify the accepted SHA-512 object and artifact identities. | Bounded schema/verifier patch and integration gate. |
| Root rotation | `tough` implements sequential root loading, old-and-new root authorization, a root-update bound, and publisher support for old signatures. | Exercise the same algorithm with every authorizing key represented by the RFC 9980 scheme, durably persisting each verified intermediate root before processing the next. Keep the accepted certifying identity and human root-transition policy as additional checks. | Existing workflow, new crypto fixtures. |
| Delegated targets | The 0.24.0 landing page says delegation is unsupported, but the same release exposes `TargetsEditor` delegation APIs and the tagged client source recursively loads and verifies delegated roles. | Qualify the source behavior. Do not model Codiquary's non-transitive grants as recursive TUF delegation; application grants remain leaf authorization checks. | Existing but documentation-inconsistent support. |
| POUF and conformance | TUF permits adopter-defined key types, schemes, and metadata formats. The official conformance suite covers the TUF client algorithm. | Publish an experimental, versioned POUF and add RFC 9980, canonical-byte, trusted-time, SHA-512, and joint-gate cases. The official suite cannot certify the custom scheme or Codiquary policy. | New profile and project-specific fixtures. |

The decisive source boundary is visible in `tough` itself. Its
[`Sign` trait](https://docs.rs/tough/0.24.0/tough/sign/trait.Sign.html) accepts
arbitrary signing implementations, and
[`SignedRole::new`](https://github.com/awslabs/tough/blob/tough-v0.24.0/tough/src/editor/signed.rs)
passes canonical metadata bytes to that trait. The signer must nevertheless
return a concrete [`schema::key::Key`](https://docs.rs/tough/0.24.0/tough/schema/key/enum.Key.html).
On the client side, the tagged
[`verify.rs`](https://github.com/awslabs/tough/blob/tough-v0.24.0/tough/src/schema/verify.rs)
looks up that concrete key and invokes its verifier. This is why a custom signer
alone cannot establish feasibility.

## Proposed experimental POUF

The experiment should draft `codiquary-tough-openpgp-pouf/0.1.0`. It is an
experimental interoperability contract, not a production profile. Following
[TAP 11](https://github.com/theupdateframework/taps/blob/master/tap11.md), it
must describe protocol, operations, usage, and formats and must be backed by a
working implementation before being presented as a POUF.

### Signature and key format

Use these experimental custom TUF names provisionally:

```json
{
  "keytype": "openpgp-rfc9580",
  "scheme": "openpgp-rfc9980-ml-dsa-65+ed25519-sha512",
  "keyval": {
    "public": "<lowercase hex of the exact binary public-certificate projection>"
  }
}
```

The projection must contain the exact RFC 9580 v6 key material, binding
signatures, and fingerprint needed by the accepted authority profile. The POUF
must reject alternate armor, packet order, extra certificates, ambiguous
projections, or another algorithm under these names.

The TUF `sig` value is lowercase hex of exactly one unarmored OpenPGP v6
detached signature packet. The verifier must require document signature type
`0x00`, RFC 9980 public-key algorithm 30, SHA-512, the expected issuer
fingerprint, and the exact canonical TUF `signed` bytes as the detached message.
It must reject trailing packets and must observe a successful Sequoia
`GoodChecksum` for the expected key rather than treating successful parsing as a
valid signature.

[RFC 9980](https://www.rfc-editor.org/rfc/rfc9980.html) assigns algorithm 30 to
ML-DSA-65+Ed25519, requires v6 keys and signatures, and requires both component
signatures to verify. The POUF must retain those requirements. A raw ML-DSA
signature, two loosely combined TUF signatures, an Ed25519 fallback, or a
classical TUF signature over a separately PQ-signed artifact would be a different
and weaker profile.

Every root, targets, snapshot, timestamp, and used delegated-targets role must be
authorized only by keys using this scheme. TUF thresholds count distinct
authorized key IDs. One composite OpenPGP signature contributes at most one
valid key toward a role threshold. A numeric threshold does not by itself prove
distinct people, operators, custody boundaries, or independent underlying key
material; the experimental policy and fixtures must state what independence they
intend to test without designing production custody.

### Canonicalization, names, and references

The POUF should retain `tough`'s tagged canonical serializer for TUF metadata and
Codiquary's JCS serializer for Codiquary objects. These are separate signed
object families. Fixtures must demonstrate that reformatting the outer TUF JSON
does not change the signed role, while any change to the canonical `signed`
object invalidates the OpenPGP signature.

The profile must preserve TUF 1.0.36 naming precisely:

- `consistent_snapshot` is optional for backward compatibility and should be
  present in new roots;
- root metadata is always fetched by version during rotation;
- timestamp metadata has the canonical unversioned transport name;
- snapshot, targets, and delegated-targets transport prefixes depend on
  `consistent_snapshot`; and
- signed metadata references remain unprefixed logical names.

Producer compare-and-swap is separate. Consistent snapshots do not serialize
writers, retain observed forks, or resolve publication conflicts.

### Time and retained state

`tough` 0.24.0 takes a fixed update-start value from its datastore and writes
verified roles during the load. The public `RepositoryLoader` exposes safe or
unsafe expiry enforcement but not a caller-supplied time. The prototype must add
an accepted trusted-time input without placing TUF persistence behind application
admission. It must durably write every verified intermediate root before
processing the next root and preserve the specified timestamp and snapshot state
transitions during refresh, including crash recovery, even when later Codiquary
policy rejects a target. Disabling TUF expiry or discarding verified TUF trust
state after an application-policy rejection is not acceptable.

Exact target bytes remain private held bytes while application policy runs.
Release of those bytes to a consumer, Codiquary accepted-current and installation
state, and installation itself require both TUF verification and the retained
Codiquary checks. The prototype must test whether those independent TUF trust-state
writes compose with the accepted atomic client-state contract and identify any
required amendment for the later adoption/contract-mapping decision; this report
does not silently redefine either state machine.

TUF timestamp freshness is mirror-freshness evidence. It is not OpenPGP signing
time, human approval, `reaffirm`, or `reaffirm-authority`. The canonical
bootstrap subject, authenticated verifier and root delivery, independently
rooted initial time, and retained monotonic floor remain Codiquary contracts.

## Joint TUF and Codiquary boundary

TUF should authenticate repository state and return exact verified target bytes.
It should not absorb policies it does not define.

| Obligation | Required owner after a TUF redesign |
| --- | --- |
| Root continuity, role thresholds, rollback/freeze checks, metadata mix-and-match resistance, target-path authorization, and verified target bytes | TUF client under the selected POUF. |
| Stable RFC 9580 fingerprint, certifying-primary/subkey lineage, scoped non-transitive grants, status and quarantine, human authorization and expiry, `reaffirm`, and `reaffirm-authority` | Codiquary authority and admission checks. |
| Producer compare-and-swap and serialization, retained fork and conflict evidence, compromise-aware historical attribution, and offline archives | Codiquary publication and history contracts. Preserve history as evidence, not as a second current selector. Do not carry the existing `release-state/v1` current-selection chain unchanged into a TUF design; exact replacement schemas belong to the adoption/contract-mapping decision. |
| Product, version, channel, purpose, and policy-profile choice | The calling application. The TUF library must not select "latest" for the application. |
| Held-byte release, accepted-current and installation state, and installation | The protected consumer boundary, after TUF verification and retained Codiquary authorization both accept the exact held bytes and application intent. Historical attribution never selects current state or authorizes installation. |

This composition avoids a second release authority. TUF authenticates acquisition
and current repository state; Codiquary applies retained non-TUF authorization
and actuation policy to the exact TUF-verified bytes. The prototype's fake gate is
deliberately narrower than the current `independent-admission/v1` input contract:
it exercises the retained checks without importing the existing
`release-state/v1` selector or claiming unmodified `admission-result/v1`
semantics. The adoption decision owns exact schema amendments. If either side
rejects or lacks required input, held bytes are not released, Codiquary
accepted-current or installation state does not advance, and the protected
installer does not run; already verified TUF trust-state transitions remain
durable.

## Smallest decisive experiments

### Rust and post-quantum integration

Use public synthetic material only. Pin TUF 1.0.36, `tough` 0.24.0 at
`98d8eb8b2ce63515d9b4981c938ef6453c5b5771`, and `sequoia-openpgp` 2.4.1 at
`0b0c8c7f038b829de2da0d28a822941d8600f3ee`. Inspect and lock all fetched source,
Cargo manifests, lockfiles, and build scripts before running them. Do not install
system software or touch a production key, trust store, provider, or host path.

1. Add a direct OpenPGP `Key` variant and strict verify branch to the pinned
   `tough` source. Add caller-supplied trusted time and required SHA-512
   verification without replacing the root, timestamp, snapshot, targets, or
   delegation algorithms or their required persistence order.
2. Implement a programmatic `KeySource`/`Sign` adapter using Sequoia. Start with
   RFC 9980 Appendix A public vectors or generated disposable fixture keys. Keep
   all test secret bytes inside the disposable fixture directory.
3. Build a repository whose four top-level roles use algorithm 30. Include one
   targets leaf and one delegated leaf, `consistent_snapshot: true`, explicit
   limits, SHA-512 references, and a JCS Codiquary object as the target.
4. From a pinned v1 root, load v2 through the existing sequential root algorithm,
   including signatures valid under both old and new composite root thresholds,
   and durably write every verified intermediate root before continuing. Refresh
   at a supplied accepted time and preserve the specified timestamp and snapshot
   state transitions. Request an application-supplied target path, consume the
   stream fully into private held bytes, and pass those exact bytes to a fake gate
   that evaluates only retained non-TUF Codiquary authorization. Preserve TUF
   trust state independently; release no held bytes and advance no Codiquary
   accepted-current or installation state unless both gates accept.
5. Prove negative cases for either composite component failing; wrong packet
   version, algorithm, hash, signature type, issuer, or key projection; duplicate
   threshold key IDs; missing SHA-512; expired roles; rollback; root skipping;
   delegated-path escape; canonical-byte drift; truncated or trailing packets;
   oversized keys, signatures, and metadata; a crash after each durable root,
   timestamp, and snapshot transition; and TUF acceptance followed by Codiquary
   rejection with TUF trust state preserved and no application-state or output
   promotion.
6. Run the official
   [`tuf-conformance`](https://github.com/theupdateframework/tuf-conformance)
   cases applicable to the unchanged client workflow, then run the custom POUF
   corpus. Record expected failures individually; do not turn an aggregate score
   into a conformance claim.

The experiment succeeds only if the crypto, clock, digest, and publisher changes
compose with the specified TUF root and refresh state transitions rather than
forking them; all metadata authority edges are RFC 9980 protected; required TUF
trust state survives crashes and later Codiquary rejection; exact bytes reach a
non-bypassable retained-policy gate; and only the conjunction releases held bytes
or advances Codiquary accepted-current and installation state. It must expose the
atomic-client-state interaction for later contract mapping, and a reviewable POUF
must describe the resulting wire and operation contract. It does not need
production custody, a provider adapter, or a complete Codiquary client.

### Representative consumer integration gate

Keep consumer integration in a second disposable prototype, blocked by the Rust
and post-quantum prototype and itself blocking adoption. Using synthetic fixtures
only, exercise release-like local file or HTTP transport and a nonprivileged
consumer adapter shaped first by Lemonade's PKGBUILD flow and the
`arch-strix-halo-pkgs` pacman flow. The application must supply its intended
product, version, channel, purpose, policy profile, and target; TUF must
authenticate the eligible description and place the exact bytes in private held
storage; and the retained Codiquary policy gate must remain non-bypassable over
those same bytes.

The fixture must preserve PKGBUILD artifact-signature verification and pacman's
native package and repository-database signatures as independent checks. It must
prove that target or intent substitution, held-byte mutation, either policy-gate
failure, or disabled native signatures cannot reach the fake consumer. It must
not provision a real package repository, install a package, cross a privilege
boundary, or mutate a host. Passing shows only that the proposed boundaries
compose for the initial consumer shapes; it does not qualify a production
transport, package repository, updater, or adapter.

## Maintenance and stop conditions

The best adoption path is an upstream `tough` verifier/key-scheme extension plus
a Codiquary-owned publisher adapter. Upstream acceptance has not been requested
or established. A direct downstream variant is suitable for the spike and could
be an acceptable temporary pin only after its diff, update cadence, advisories,
and rebase burden are measured. Sequoia's
[leaf-crate crypto-backend selection](https://docs.rs/crate/sequoia-openpgp/2.4.1/source/build.rs)
and
[LGPL-2.0-or-later licensing](https://docs.rs/crate/sequoia-openpgp/2.4.1/source/Cargo.toml)
also require normal build and distribution review.

Stop and retain the non-TUF baseline if either experiment shows any of the
following:

- RFC 9980 support requires changing TUF's root or refresh algorithm rather than
  adding a key scheme;
- all-role PQ protection requires a classical fallback or a second authority
  interpretation;
- required TUF trust-state transitions cannot be durably persisted and recovered
  independently while held-byte release and Codiquary application state remain
  gated, or their interaction with the accepted atomic client-state contract
  cannot be characterized for the adoption decision;
- SHA-512 or the exact OpenPGP packet profile cannot be enforced before the
  install boundary;
- the publisher must import production secret keys into general repository
  tooling;
- the POUF cannot make `tough`, Sequoia, and Codiquary byte semantics
  unambiguous;
- the representative synthetic consumer fixture can compose the layers only by
  bypassing application intent, weakening retained Codiquary policy, disabling
  PKGBUILD or pacman native signatures, provisioning a real repository, or
  installing packages; or
- the patch cannot be upstreamed and its measured downstream maintenance burden
  is disproportionate to the TUF client and conformance code being reused.

## Credible alternative

[`sigstore-tuf` 0.11.0](https://docs.rs/sigstore-tuf/0.11.0/sigstore_tuf/)
is the credible client alternative. It exposes an explicit time parameter on
`Updater::refresh`, implements root chaining and bounded delegated-target search,
and documents its canonical-JSON and cache behavior clearly. It does not expose
a repository editor, and its inspected verifier path uses the Sigstore classical
key stack rather than RFC 9980 OpenPGP. Pairing a patched `sigstore-tuf` client
with a patched `tough` publisher or a new Rust publisher creates two metadata
models and two custom integration seams. It should replace `tough` as the
prototype client only if the `tough` clock or verifier changes prove invasive.

## Limitations and remaining decisions

This is source-backed feasibility research. No crate source was downloaded into
the repository, and no build, prototype, conformance run, key operation,
publication, provider integration, or installation was performed. The local
Cargo cache did not contain the pinned candidates. Context7 documentation fetch,
GitHub source fetch through Git, and Firecrawl exact-page access each failed on
their first network attempt; official tagged sources, docs.rs, GitLab, RFC Editor,
and TUF pages were inspected through the read-only web fallback instead.

No new policy decision is needed before the two proposed disposable prototypes;
each remains separate work. Adoption will require one explicit choice after both
sets of evidence exist: require an upstream verifier extension, or accept
ownership of a version-pinned downstream patch with a stated maintenance budget.
The later adoption decision must also settle POUF interoperability, authorized
key-ID thresholds and any separate operator/custody policy, the mapping between
TUF's durable trust state and the accepted atomic client-state contract, retirement
of the overlapping `release-state/v1` selector, and exact amendments to current
admission contracts. This report does not decide those policies.

## Primary sources

- [TUF specification 1.0.36](https://github.com/theupdateframework/specification/blob/v1.0.36/tuf-spec.md)
- [TAP 11: POUFs](https://github.com/theupdateframework/taps/blob/master/tap11.md)
- [`tough` 0.24.0 release](https://github.com/awslabs/tough/releases/tag/tough-v0.24.0),
  [API](https://docs.rs/tough/0.24.0/tough/), and
  [tagged verifier source](https://github.com/awslabs/tough/blob/tough-v0.24.0/tough/src/schema/verify.rs)
- [`tuftool` 0.17.0](https://docs.rs/crate/tuftool/0.17.0)
- [`sequoia-openpgp` 2.4.1 NEWS](https://docs.rs/crate/sequoia-openpgp/2.4.1/source/NEWS),
  [feature flags](https://docs.rs/crate/sequoia-openpgp/2.4.1/features),
  [Cargo manifest](https://docs.rs/crate/sequoia-openpgp/2.4.1/source/Cargo.toml),
  [build script](https://docs.rs/crate/sequoia-openpgp/2.4.1/source/build.rs), and
  [release tag](https://gitlab.com/sequoia-pgp/sequoia/-/tags/openpgp%2Fv2.4.1)
- [RFC 9580](https://www.rfc-editor.org/rfc/rfc9580.html) and
  [RFC 9980](https://www.rfc-editor.org/rfc/rfc9980.html)
- [`sigstore-tuf` 0.11.0](https://docs.rs/sigstore-tuf/0.11.0/sigstore_tuf/)
- [`sigstore-crypto` 0.11.0](https://docs.rs/sigstore-crypto/0.11.0/sigstore_crypto/)
- [Official TUF client conformance suite](https://github.com/theupdateframework/tuf-conformance)
