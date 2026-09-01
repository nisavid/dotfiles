# SCITT adoption for Crypto Ops and Release Ops

**Research date:** 2026-08-31

**Status:** Public planning research. This note audits accepted mechanisms; it
does not amend an issue resolution, select a service, claim conformance, or
authorize implementation or deployment.

## Verdict

SCITT now gives Crypto Ops a standards-defined evidence layer, not a replacement
release authority. The first public release should keep the accepted strict JCS,
SHA-512, OpenPGP RFC 9980 authority and the #210 retained-state verifier. It
should reserve a typed SCITT evidence profile and publish disposable bridge
fixtures now, while keeping every live transparency service optional and outside
the ordinary release path.

The strongest later architecture is an exact-byte composition:

1. the accepted OpenPGP release graph remains authoritative;
2. an [RFC 9995 COSE Hash Envelope](https://www.rfc-editor.org/rfc/rfc9995.html)
   signed by a distinct SCITT evidence issuer binds the SHA-512 digest and
   media type of one frozen `signature-envelope/v1` object, while the relying
   party cross-checks its byte length from the authoritative #209 descriptor;
3. a transparency service registers that SCITT Signed Statement and returns an
   [RFC 9942](https://www.rfc-editor.org/rfc/rfc9942.html) receipt; and
4. the relying party verifies the SCITT evidence and then independently
   re-verifies the complete #209 OpenPGP authority, state, and admission graph.

That composition uses SCITT's registered names, COSE shapes, receipt headers,
media types, and service protocol instead of inventing parallel log objects. It
does not let a transparency-service receipt establish release authorization,
current selection, signing time, withdrawal state, safe execution, or consumer
permission.

A SCITT/COSE-native release authority is not ready for the first public release.
It would require a breaking successor protocol that redefines root and grant
continuity, current selection, withdrawal, refresh, and historical policy. Pure
ML-DSA is standardized for COSE, but the selected ML-DSA-65+Ed25519 composite is
only an active Internet-Draft for JOSE and COSE. No standardized hybrid SCITT
profile exists, and no public service found here satisfies the required hybrid
post-quantum, independent-witness, retained-checkpoint, privacy, availability,
and historical-verification contract.

## Decision scope and evidence

This audit treats the following as accepted intent while re-examining their
mechanisms:

- [#203 historical verification and external evidence](https://github.com/nisavid/dotfiles/issues/203#issuecomment-5463564990)
- [#204 canonical publication](https://github.com/nisavid/dotfiles/issues/204#issuecomment-5469266482)
- [#206 release-authority topology](https://github.com/nisavid/dotfiles/issues/206#issuecomment-5465835347)
- [#207 public-core, profile, and qualification boundaries](https://github.com/nisavid/dotfiles/issues/207#issuecomment-5470521497)
- [#209 release objects and independent admission](https://github.com/nisavid/dotfiles/issues/209#issuecomment-5474608513)
- [#210 client bootstrap, refresh, and retained state](https://github.com/nisavid/dotfiles/issues/210#issuecomment-5474715429)
- accepted [#212 Base Loadout consumer profile](https://github.com/nisavid/dotfiles/issues/212#issuecomment-5494463333)

The local starting points are the [cross-precedent audit](CRYPTO_RELEASE_OPS_PRECEDENT_AUDIT.md),
the [generic consumer research](../agent-equipment/research/generic-release-trust-components.md),
and the current source [context](../agent-equipment/CONTEXT.md),
[architecture](../agent-equipment/ARCHITECTURE.md), and
[implementation handoff](../agent-equipment/IMPLEMENTATION_HANDOFF.md).

Only primary public sources support current standards and implementation claims:
RFC Editor publications, IETF Datatracker and IANA registries, official working-
group material, and first-party implementation or service documentation. A
repository's existence, release count, or self-description is not conformance or
operational qualification.

## Standards and document maturity

The status labels matter. “Standards Track” on an Internet-Draft is an intended
destination, not a published standard.

| Document | Status on 2026-08-31 | Relevance |
| --- | --- | --- |
| [RFC 8949](https://www.rfc-editor.org/rfc/rfc8949.html) | Internet Standard, STD 94 | CBOR data model and deterministic-encoding guidance. CBOR itself does not select one universal canonical encoding. |
| [RFC 9052](https://www.rfc-editor.org/rfc/rfc9052.html) and [RFC 9338](https://www.rfc-editor.org/rfc/rfc9338.html) | Internet Standard, STD 96 | COSE structures/process and countersignatures. A SCITT receipt is its own COSE_Sign1 object, not an RFC 9338 countersignature. |
| [RFC 9053](https://www.rfc-editor.org/rfc/rfc9053.html) | Informational | Initial COSE algorithms. New profiles must also follow later IANA registrations and RFC 9864's fully specified identifiers. |
| [RFC 8610](https://www.rfc-editor.org/rfc/rfc8610.html) | Proposed Standard | CDDL notation used to define SCITT and receipt object shapes. |
| [RFC 9942](https://www.rfc-editor.org/rfc/rfc9942.html) | Proposed Standard, June 2026 | COSE receipt and VDS-proof framework; a normative dependency of SCITT. |
| [RFC 9943](https://www.rfc-editor.org/rfc/rfc9943.html) | Proposed Standard, June 2026 | SCITT architecture, roles, Signed Statement and Transparent Statement formats, and registration/verification flows. |
| [RFC 9162](https://www.rfc-editor.org/rfc/rfc9162.html) | Experimental | Certificate Transparency v2 Merkle tree, inclusion proofs, consistency proofs, monitoring, and split-view caveats. It is the only currently registered RFC 9942 VDS. |
| [RFC 9921](https://www.rfc-editor.org/rfc/rfc9921.html) | Proposed Standard, February 2026 | RFC 3161 timestamp headers for COSE, with distinct completed-signature and payload-first semantics. |
| [RFC 9964](https://www.rfc-editor.org/rfc/rfc9964.html) | Proposed Standard, May 2026 | Pure ML-DSA COSE and JOSE algorithms; not a classical-plus-PQ hybrid. |
| [RFC 9995](https://www.rfc-editor.org/rfc/rfc9995.html) | Proposed Standard, July 2026 | COSE Hash Envelope; the clean standards bridge to an exact OpenPGP object. |
| [SCRAPI-11](https://datatracker.ietf.org/doc/draft-ietf-scitt-scrapi/) | Active SCITT WG Internet-Draft; intended Proposed Standard; in the RFC Editor queue awaiting a first editor | HTTP key discovery, registration, and receipt resolution. It is not yet an RFC. |
| [CCF receipt profile-04](https://datatracker.ietf.org/doc/draft-ietf-scitt-receipts-ccf-profile/) | Active SCITT WG Internet-Draft; intended Proposed Standard; IETF Last Call through 2026-09-07 | CCF-specific inclusion receipt and requested VDS identifier 2. It is not yet an RFC or registered VDS. |
| [SCITT software use cases-03](https://datatracker.ietf.org/doc/draft-ietf-scitt-software-use-cases/) | Expired and archived Internet-Draft since 2024 | Historical WG input, not a current protocol or profile. |

The [SCITT WG document page](https://datatracker.ietf.org/wg/scitt/documents/)
shows two live WG drafts: SCRAPI and the CCF receipt profile. The additional
related documents listed there are individual submissions or other streams, not
SCITT WG standards. They may inform experiments but cannot silently extend the
SCITT conformance claim.

### Current PQ COSE boundary

[RFC 9964](https://www.rfc-editor.org/rfc/rfc9964.html) registers pure
ML-DSA-44, ML-DSA-65, and ML-DSA-87 as COSE algorithms -48, -49, and -50; all
are currently Recommended in the [IANA COSE Algorithms registry](https://www.iana.org/assignments/cose/).
[RFC 8778](https://www.rfc-editor.org/rfc/rfc8778.html) also defines HSS/LMS for
COSE, but its finite state and strict non-reuse requirements make cloned or
rolled-back release signers an unattractive match for this system.

The active [PQ/T composite signatures draft-03](https://datatracker.ietf.org/doc/draft-ietf-jose-pq-composite-sigs/)
does cover both JOSE and COSE and proposes ML-DSA-65-Ed25519 with SHA-512 and a
COSE value of -58. The value is not assigned. Both components must verify, and
the component keys must be freshly generated for the composite and must not be
used, imported, or exported in another combination or standalone context. The
draft also says the construction is unsuitable where non-repudiation or
signature uniqueness is required. That wording is in tension with RFC 9943's
description of a Signed Statement as non-repudiable and must be resolved by the
standards or by an explicit application security analysis before adoption. It
also rules out reusing the accepted RFC 9980 OpenPGP component keys in a COSE
composite.

The [SLH-DSA draft-10](https://datatracker.ietf.org/doc/draft-ietf-cose-sphincs-plus/)
and [FN-DSA draft-04](https://datatracker.ietf.org/doc/draft-ietf-cose-falcon/)
are active COSE WG work, not RFCs. None defines a SCITT release-authority
profile. General COSE multi-signature or countersignature capability does not
fill the gap because RFC 9943 fixes a Signed Statement as COSE_Sign1 and does
not specify all-components-required hybrid verification or downgrade handling.

## What RFC 9943 and RFC 9942 actually define

### Domain glossary and local mapping

| SCITT term | Standard meaning | Crypto Ops / Release Ops mapping and guardrail |
| --- | --- | --- |
| Artifact | A physical or non-physical supply-chain item. | A release artifact, an exact protocol object, or another subject of evidence. It is not automatically an admitted or executable candidate. |
| Statement | Any serializable information about an Artifact, tagged with a relevant media type. The TS may treat its payload as opaque or encrypted. | An assertion about one exact #209 object, preferably a standard hash envelope. It is not one of the twelve #209 families merely because it is logged. |
| Signed Statement | A CBOR-tag-18 COSE_Sign1 whose protected CWT Claims header includes `iss` and `sub`. | A new SCITT evidence object signed by a **SCITT statement issuer**. It is not `signature-envelope/v1`, and its signature does not validate the enclosed OpenPGP graph unless a profile requires that separate check. |
| Transparent Statement | A Signed Statement augmented with one or more receipts in unprotected header 394. | A transportable evidence bundle. Because receipts are unprotected additions and can change, it must not be the immutable `release-envelope/v1` identity. |
| Issuer | The organization, device, user, reviewer, auditor, or endorser that signs a Statement; identified by protected CWT `iss`. | Always qualify this as **SCITT statement issuer**. It is distinct from the OpenPGP release signer and from the TS receipt issuer. |
| Subject | The issuer-defined `sub` identifier used to correlate Statements about an Artifact. | A stable, profile-defined identifier for the exact object or stream. It does not replace the #209 SHA-512 content identity or product/channel/purpose tuple. |
| Transparency Service (TS) | The entity that applies registration policy, maintains and extends a VDS, and signs receipts. | An external-evidence producer with its own separately bootstrapped receipt trust root. It is not the canonical release publisher, release signer, or verifier-update authority. |
| Registration Policy | The TS's admission precondition, evaluated before insertion. The operator owns its format and additional checks. | **TS registration policy**, never release authorization or relying-party admission. Passing it says that the service accepted the Signed Statement under its then-current policy. |
| Receipt | A tagged COSE_Sign1 signed proof of one or more VDS properties. | Always call it a **SCITT receipt**. It is neither a publication readback receipt nor Base Loadout's terminal release receipt. |
| Relying Party / Verifier | A consumer that trusts selected issuer and TS identities, verifies evidence, and applies arbitrary local policy. | The generic verifier is a stricter RP: it must re-run #209 admission and may never let receipt validity upgrade the four-result outcome. |
| Auditor | A specialized RP that checks all Transparent Statements or replays the sequence for correctness and consistency. | A log-audit role. It does not become the #207 qualification authority or a Base Loadout authority merely by auditing. |
| Statement Sequence | The TS registration history. | Supplemental observation order only. It is not the #209 alternating global state chain and does not select current release state. |
| VDS / VDP | A registered verifiable data-structure algorithm and proofs of properties such as inclusion or consistency. | A proof substrate. The profile, prior retained roots, service keys, monitoring, and local policy determine what a particular proof establishes. |

### Required wire shape

A conforming SCITT Signed Statement is COSE_Sign1. Its protected header carries
the CWT Claims parameter 15 with `iss` claim 1 and `sub` claim 2. It carries
`kid` if neither `x5t` nor `x5chain` identifies the verification key; X.509 use
requires the RFC 9360 certificate headers and path validation. RFC 9943
registers:

- `application/scitt-statement+cose`, file extension `.scitt`;
- `application/scitt-receipt+cose`, file extension `.receipt`; and
- CoAP Content-Format identifiers 277 and 278.

RFC 9942 registers COSE header parameters `receipts` 394, `vds` 395, and `vdp`
396. The live IANA VDS registry contains only `RFC9162_SHA256` identifier 1,
with inclusion proof label -1 and consistency proof label -2. The receipt and
VDS profile—not the application—own those identifiers and proof encodings.

New profiles should use fully specified live IANA algorithm identifiers. In
particular, [RFC 9864](https://www.rfc-editor.org/rfc/rfc9864.html) deprecates
polymorphic COSE `ES256` and `EdDSA` in favor of identifiers such as `ESP256`
(-9) and `Ed25519` (-19). Examples in older or newly published documents that
still show -7 or -8 are not a reason for a new profile to ignore the live
registry.

### Registration and verification flow

1. An issuer serializes a Statement, selects a protected media type and subject,
   and signs the protected headers and payload as COSE_Sign1.
2. A client submits that Signed Statement. Client authentication and
   authorization are implementation-specific in RFC 9943 and remain out of
   scope in SCRAPI.
3. The TS verifies the COSE signature and protected identity, authenticates the
   issuer under its registration anchors, optionally validates the payload for
   domain-specific checks, and applies its latest registered policy.
4. The TS empties the Signed Statement's unprotected header before inserting
   the statement into its sequence, inserts it into its VDS, and only then
   releases a receipt. Receipt creation may be asynchronous, but every
   registered Signed Statement must have a receipt available.
5. Anyone holding the Signed Statement and receipt can create a Transparent
   Statement by placing the receipt in unprotected header 394. One Signed
   Statement may collect receipts from multiple services.
6. The RP trusts at least one selected receipt issuer key, verifies the
   VDS-specific proof and receipt signature, and applies its own issuer,
   payload, history, and local-state policy.
7. An Auditor obtains the sequence, policies, anchors, and authentication
   collateral needed to replay registration and check consistency.

RFC 9943 permits an RP to accept one receipt without re-verifying the Signed
Statement. The Crypto Ops profile must prohibit that shortcut: it must verify
the SCITT statement issuer, exact RFC 9995 preimage binding, underlying #209
OpenPGP signature and grant, current or historical state, and installed policy.

### Registration policy is not relying-party policy

The TS must authenticate Signed Statements and maintain a registration policy,
even if the additional policy is “allow every authenticated submission.” It
must make registration-policy and trust-anchor changes transparent and retain
enough policy and collateral for audit replay. The policy's encoding and extra
checks remain operator-defined.

The RP separately decides which statement issuers, TS identities, VDS profiles,
and statements it trusts. It may use the envelope, receipt, payload, and local
state in arbitrary post-verification policy. Therefore:

- a TS registration anchor is not the release trust anchor;
- service acceptance is not `accepted-current`;
- a transparent service policy can be auditable and still be unsuitable for
  release admission; and
- a later adopter profile may require one or more SCITT services, but that
  criticality comes from installed RP policy, not a publisher-controlled field.

### Receipt and VDS semantics

For `RFC9162_SHA256`, an inclusion proof encodes tree size, leaf index, and an
inclusion path. The verifier applies the proof to the exact candidate entry to
reconstruct the Merkle root, then verifies the receipt signature over that
root. A consistency proof encodes old size, new size, and a consistency path;
it is meaningful only relative to an older trusted root or proof. A valid
signature over an invalid proof is failure, not partial success.

RFC 9943 requires the abstract VDS to be append-only, non-equivocating, and
replayable. A single inclusion receipt does not demonstrate a globally common
view. RFC 9162 requires monitors to inspect entries and roots and says
conflicting views require clients to compare signed tree heads—gossip or an
equivalent cross-check, which RFC 9162 does not define. Consistency proves that
one later root extends one earlier root; it does not discover a fork presented
only to somebody else. Witness policy, checkpoint exchange, and monitor
operations remain application and service obligations.

RFC 9942 standardizes the receipt container and one VDS profile, not receipt
freshness, status, suspension, or revocation policy. RFC 9943 permits receipt
keys, algorithms, validity, and headers to change when a fresh receipt is
issued. It even permits a service recovering from a receipt-key compromise to
roll its sequence back before compromise and issue fresh receipts. That
recovery is incompatible with #210 automatic continuity unless the client
retains the old root and evidence, verifies successor inclusion, or requires an
explicit manual rebootstrap.

### Privacy and availability limits

The TS is trusted with the confidentiality of submitted Signed Statements.
Hash-only VDS storage can limit retained content, but submission timing,
ordering, subjects, header metadata, and correlations with adjacent stores can
still reveal build, signing, and upload activity. RFC 9942 proofs may reveal log
size, and profile headers may reveal service or entry metadata.

Neither RFC supplies an availability objective, durable key-retention promise,
public enumeration guarantee, witness service, notification mechanism, or
universal trust-root distribution channel. A retained receipt is offline-
verifiable only when the relying party has retained the right TS key, algorithm
support, exact entry, VDS profile, and any prior root needed by the claimed
property. A service outage can block required registration or fresh evidence;
it cannot make missing evidence silently valid.

### What SCITT does not assert

SCITT does not assert that:

- the Statement is true, complete, safe, current, or authorized for release;
- VDS order equals issuance, signing, publication, or release-state order unless
  the registration policy explicitly establishes that meaning;
- all Statements an issuer created were registered;
- a receipt time is the OpenPGP signature creation time or an RFC 3161 trusted
  timestamp;
- the TS registration policy equals the RP's release or consumer policy;
- a receipt establishes current-release selection, revocation, withdrawal,
  freeze, re-selection, or freshness;
- inclusion alone detects split views;
- the TS stores the complete payload or provides the #209 complete archive; or
- verification authorizes installation, execution, archive mutation, or any
  Base Loadout release receipt.

## Live API and receipt profiles

### SCRAPI-11

[SCRAPI-11](https://datatracker.ietf.org/doc/draft-ietf-scitt-scrapi/) is
advanced but still mutable Internet-Draft work. Its mandatory HTTP resources
are:

- `GET /.well-known/scitt-keys` for an `application/cbor` COSE Key Set;
- `GET /.well-known/scitt-keys/{kid}` for one COSE key;
- `POST /entries` for synchronous `201` receipt or asynchronous `202` plus
  `Location`; and
- `GET` of that location for `200` receipt, `204` still running, or `404`
  unknown/failed registration.

Errors use RFC 9290 Concise Problem Details. Clients must handle retries,
`Retry-After`, rate limiting, and ambiguous asynchronous outcomes without
assuming that HTTP acceptance means VDS insertion. The well-known URI is
already in the [IANA registry](https://www.iana.org/assignments/well-known-uris/),
but the registration still references the unpublished draft.

SCRAPI intentionally leaves VDS internals, registration-policy contents,
authentication, and replay-sensitive application semantics out of scope.
Unsigned HTTP routes or headers may dispatch processing but cannot select the
authoritative application profile. The draft says retired receipt keys should
remain available while their receipts matter and makes the RP responsible for
retaining them; cache headers are not a key-availability promise.

### CCF receipt profile-04

The [CCF profile](https://datatracker.ietf.org/doc/draft-ietf-scitt-receipts-ccf-profile/)
requests `CCF_LEDGER_SHA256` VDS identifier 2 and defines an inclusion proof
whose leaf commits a CCF internal transaction hash, internal evidence, and the
SHA-256 hash of application data. Identifier 2 is not in the live IANA VDS
registry. The draft defines inclusion, not the generic RFC 9942 consistency
proof for that VDS.

Its security model matters more than its format. CCF relies on TEE-protected
policy evaluation and receipt keys plus distributed consensus. The draft says
TEE compromise can produce divergent invalid branches and a malicious operator
can start a successor network from an earlier prefix. Clients must regularly
audit, assess attestation, retain prior receipts, and verify that the successor
includes the last state they knew. This profile is useful implementation input,
not a qualified split-view solution.

## Reference graph: what is reusable here

| Standard or work | Actual SCITT role | Adoption ruling |
| --- | --- | --- |
| CBOR RFC 8949, COSE RFC 9052, and CDDL RFC 8610 | Native bytes, signature structure, and schemas. | Directly adopt inside the SCITT adapter. Define one deterministic CBOR profile and immutable test vectors; do not let alternative CBOR encodings identify the same signed object. |
| CWT RFC 8392 and CWT Claims in COSE Headers RFC 9597 | Protected `iss` and `sub` identity claims. | Directly adopt. Specify stable URI-shaped issuer/subject semantics and key binding; do not substitute local OpenPGP fingerprint meaning implicitly. |
| COSE `typ` RFC 9596 and X.509 headers RFC 9360 | Type domain separation and conditional certificate carriage. | Require `typ` in the local profile. Use RFC 9360 only for an X.509 issuer profile; a bare `kid` still needs an out-of-band key-discovery and trust contract. |
| RFC 9942 plus RFC 9162 | Receipt, VDS, inclusion, and consistency proof shapes. | Directly adopt for SCITT evidence. Treat SHA-256 as the registered proof-tree algorithm, never the authoritative #209 content identity. |
| RFC 9995 | Standard COSE signature over a payload digest, with protected hash algorithm, preimage content type, and optional location. | Directly adopt as the bridge. Use SHA-512 over exact frozen `signature-envelope/v1` JCS bytes and bind its media type; keep byte length in the authoritative #209 descriptor and cross-check it against the recovered preimage. Omit locator authority. RFC 9995 forbids ordinary COSE `content_type` label 3 in a Hash Envelope and uses `preimage-content-type` label 259 instead. |
| RFC 9921 and RFC 3161 | Two COSE timestamp orderings. | Complementary. `3161-ctt` timestamps the CBOR-encoded completed COSE signature field; `3161-ttc` timestamps the payload before COSE signing and is not evidence that the signature already existed. Keep #203's RFC 3161 token over completed OpenPGP signature bytes as separate authority evidence. |
| RFC 9964 | Pure ML-DSA signatures for a SCITT statement issuer or TS receipt issuer. | Reusable when implementations and services support it, but not a replacement for RFC 9980 hybrid authority. End-to-end PQ claims must cover issuer, receipt/checkpoint, witness, retained evidence, and renewal—not only the inner release signature. |
| RFC 9162 monitoring model | Full-log inspection, root consistency, and split-view caveats. | Reuse as a threat and test model. Do not call CT itself a generic release log or claim that a lone receipt is witnessed. |
| RATS epoch-marker draft | An informative SCRAPI suggestion for replay-sensitive protected time. | No direct first-release role. It does not replace #210 trusted time or #203 exact-signature timestamps. |
| EAT, CoRIM, and SUIT | None is a normative RFC 9942/9943 dependency or SCITT release-authority component. | Deliberately exclude. A CCF deployment may use attestation operationally, but SCITT does not require importing EAT/CoRIM authority or SUIT command semantics. |

## Implementations and services

| Source | Current evidence | Adoption significance |
| --- | --- | --- |
| [IETF SCITT WG examples](https://github.com/ietf-wg-scitt/examples) | Official repository with signed/transparent examples from Microsoft and DataTrails plus positive and negative `scitt-cose` vectors. No release or conformance certification. | Best public seed corpus. Use it before local bridge vectors; do not infer service qualification. |
| [Microsoft scitt-ccf-ledger](https://github.com/microsoft/scitt-ccf-ledger), release [0.19.0](https://github.com/microsoft/scitt-ccf-ledger/releases/tag/0.19.0) | Actively maintained CCF application. Its own [alignment page](https://github.com/microsoft/scitt-ccf-ledger/blob/main/docs/scitt.md) still names architecture draft-11, receipt draft-08, CCF profile-03, and SCRAPI-09. The development launcher uses an ad hoc governance key, disables API authentication, and applies a permissive policy. | Strongest disposable service implementation found, but only dev/interop evidence until exact final-RFC/current-draft behavior is demonstrated. |
| [Microsoft Signing Transparency](https://learn.microsoft.com/en-us/azure/confidential-ledger/about-microsoft-signing-transparency-ledger) | First-party operated GA service on CCF. Microsoft says verification is currently scoped to specific Microsoft services and uses the draft CCF profile. | Real operational maturity, but not an open generic registration service or a conformance certificate for this profile. |
| [DataTrails SCITT action](https://github.com/datatrails/scitt-action) | Describes itself as Preview pending SCRAPI; requires service credentials; its receipt-file output is “not currently implemented.” | Cross-producer example source only, not a qualified receipt adapter. |
| [SCITT API emulator](https://github.com/scitt-community/scitt-api-emulator) | Archived and unmaintained since 2024. | Historical prototype only. Exclude from new qualification. |
| [Action State `scitt-cose`](https://github.com/action-state-group/scitt-cose) | New third-party verification library, release 0.2.2; explicitly not a TS. It recognizes ML-DSA identifiers but says ML-DSA signing is not implemented. Some of its vectors are vendored in the WG examples. | Useful second verifier candidate after source review; insufficient evidence of broad algorithm or service maturity. |
| [Action State `capsule-anchor`](https://github.com/action-state-group/capsule-anchor) | Alpha 0.1.0 source and a public instance; no repository release. It uses custom `/register` and `/transparency/register-statement` routes, DID key discovery, an open policy, Ed25519, and SHA-256 rather than the SCRAPI resource and trust contract. | Useful hostile/interop input only. Its self-description as SCITT does not establish SCRAPI or adopter-profile conformance, witnessing, key retention, or service qualification. |

No primary-source conformance program or current matrix was found for RFC 9942,
RFC 9943, SCRAPI-11, and an adopter-selected profile together. No public service
found here is qualified for this project's exact-byte, independently witnessed,
hybrid-PQ, retained-history, privacy, availability, and exit requirements. That
is an evidence gap, not proof that no other service exists.

## Functional crosswalk

The classification describes the best relationship, not permission to change an
accepted object in place.

| Existing contract | Classification | Precise mapping |
| --- | --- | --- |
| `release-manifest/v1` | SCITT profile/extension | It may be the preimage or subject of a Signed Statement. SCITT does not define its products, channels, selectors, artifact completeness, JCS encoding, or SHA-512 identity. |
| `authority-grant/v1` | Semantic alignment | A grant can be logged and observed, and a TS can authenticate its SCITT issuer. TS registration anchors cannot replace the root-issued OpenPGP binding plus monotonic grant state. |
| `authority-state/v1` | Complementary integration | Inclusion and consistency can corroborate external observation. TS sequence order is not the authoritative generation chain and cannot express the accepted positive/subtractive powers. |
| `root-transition/v1` | Complementary integration | SCITT may evidence both signed transition objects and their observation. It defines no old-plus-new-root authorization, activation generation, or manual-rebootstrap rule. |
| `release-state/v1` | Conflict | Replacing it with same-subject later SCITT Statements would lose current selection, `valid_until`, reaffirm, freeze, withdrawal, reselect, and terminal-manifest semantics. Logging it as an exact object is complementary evidence. |
| `state-index/v1` | Outside SCITT | A VDS entry or transaction position is not the unsigned content-addressed retrieval projection, and neither can select current state. Discovery and change notification remain out of RFC 9943. |
| `signature-envelope/v1` | Conflict | A SCITT Signed Statement is COSE_Sign1, while this envelope indexes exact detached OpenPGP RFC 9980 bytes and lineage. Do not replace or dual-interpret it. Use its exact JCS bytes as the RFC 9995 preimage. |
| `release-envelope/v1` | Conflict | A Transparent Statement gains receipts in an unprotected header and can have multiple byte representations. It cannot replace the immutable approval graph or its identity. |
| `evidence-index/v1` | Direct SCITT adoption | This is the integration home. Define entries for exact SCITT Signed Statement and receipt bytes, their registered media types, VDS/profile, TS key/policy collateral, checkpoints/consistency, and monitor or witness evidence. Installed policy decides criticality. |
| `archive-index/v1` | Complementary integration | Archive the complete #209 closure plus SCITT statement, receipt, TS key history, registration policy and anchors if policy replay is claimed, prior roots, consistency/witness material, and profile versions. A TS is not the complete archive. |
| `admission-request/v1` | Outside SCITT | SCITT RP policy is not the deterministic, caller-supplied trust-context request. Preserve network-free pure evaluation. |
| `admission-result/v1` | Outside SCITT | A registration response or receipt-verification Boolean is not `accepted-current`, `attributed-historical`, `rejected`, or `indeterminate`. Valid SCITT over invalid core stays rejected; missing profile-required SCITT evidence is indeterminate; invalid optional evidence is a note. |
| #210 bootstrap, refresh, and retained state | Complementary integration | Retain TS roots, historical receipt keys, checkpoints, and fork observations as separately versioned external-evidence state. SCRAPI key discovery is retrieval, not trust bootstrap, and must not overwrite the release high-water chain. |
| #207 qualification records | SCITT profile/extension | A qualification record may be a Statement, but SCITT does not decide who has qualification authority, threshold, scope, supersession power, or support obligations. |
| #204 publication receipts | Outside SCITT | These are provider readback and promotion-operation records. They may themselves be logged, but they do not become SCITT receipts and a SCITT receipt does not prove canonical promotion. |
| #203 RFC 3161 evidence | Complementary integration | Keep the exact completed OpenPGP signature as the timestamp subject. RFC 9921 applies only if the later COSE wrapper also needs its own timestamp and must preserve CTT/TTC ordering semantics. |
| Base Loadout release receipt | Outside SCITT | It is a terminal record emitted only after #121's independent complete release-tuple validation and #122's durable create-only archive. A SCITT receipt is prior external evidence and must never grant launcher, archive, application-actuation, fitting, migration, or release-receipt capability. |

## Architecture comparison

### A. SCITT/COSE-native release authority

This can be designed as a future experimental successor profile, but SCITT does
not supply the missing release-authority protocol.

| Property | Finding |
| --- | --- |
| Standards conformance | COSE and SCITT provide standard envelopes and evidence. Root/grant topology, release state, current selection, revocation, refresh, and actuation would still be a private application profile. The existing JCS/OpenPGP object version could not acquire a second interpretation. |
| Hybrid PQ | RFC 9964 supplies pure ML-DSA. The exact ML-DSA-65+Ed25519 COSE composite is an unassigned active draft with fresh-key and non-repudiation limitations. No final hybrid SCITT profile exists. |
| Trust roots | It introduces at least a COSE statement-issuer root and TS receipt root. A service's registration anchors are a third policy plane unless deliberately unified, and unification would enlarge service authority. |
| Offline verification | Possible only with the complete object, issuer key/chain, TS key history, VDS profile, proofs, prior roots, and application state. SCITT does not archive or distribute that closure for the adopter. |
| Split views | Inclusion is insufficient. Consistency, retained checkpoints, monitors, and independent witnesses remain necessary. CCF adds TEE and successor-network assumptions. |
| Bootstrap and currentness | RFC 9943 bootstrap is for the TS's policy and anchors, not the release client's stable root/domain ceremony. SCITT has no current-release selector. |
| Revocation and withdrawal | Receipt validity/status and key revocation are out of scope. Same-subject supersession is advisory and cannot express terminal #209 withdrawal without a new profile. |
| Historical attribution | Registration proves inclusion, not issuance order, signing time, or authorization at a claimed time. The full accepted history and cutoff policy would remain. |
| Privacy and availability | A mandatory service learns timing and metadata and becomes a release-path dependency. Hash envelopes reduce content exposure but not correlation. |
| Operations and maturity | Current API and CCF profiles are drafts. One scoped GA service exists, but no qualified generic service or hybrid witness topology was found. |

Disposition: **deliberately exclude from the first public release**. Reconsider
only as a breaking successor profile after the COSE hybrid, service, witness,
bootstrap, and lifecycle contracts are independently mature. It is not a way to
avoid the separate TUF conformance-versus-delta decision.

### B. TUF/OpenPGP authority with SCITT evidence

This is the best eventual composition. “TUF/OpenPGP authority” is conditional:
the project must first decide whether the #209 role and client model is a
conforming TUF POUF or an explicit non-TUF design. It must not operate TUF and
#209 as competing current-authority planes.

| Property | Finding |
| --- | --- |
| Standards conformance | Each layer keeps one job: TUF or its explicit delta owns updater-role/state logic; RFC 9980 OpenPGP owns release signatures; RFC 9995/9943/9942 own the transparency evidence shape. |
| Hybrid PQ | The authoritative release remains RFC 9980 hybrid. The SCITT statement issuer can later use pure ML-DSA, but the VDS, receipt signer, witnesses, and renewals must also be assessed before claiming end-to-end PQ evidence. |
| Trust roots | Preserve and name three domains: release trust anchor, SCITT statement issuer, and TS receipt issuer. Bootstrap and rotate each independently; never discover a required TS root from the same untrusted receipt. |
| Offline verification | Strong when the #209 archive also retains exact SCITT bytes, keys, policies/collateral needed for the claimed check, prior roots, consistency/witness material, and profile versions. |
| Split views | Additive: retained SCITT roots can expose inconsistent continuations, and witnesses can compare views. The accepted client high-water state remains necessary. |
| Bootstrap and currentness | #210 remains authoritative. SCRAPI retrieves keys and receipts but neither selects the trust anchor nor the current release. |
| Revocation and withdrawal | #206/#209 lifecycle state remains authoritative. A valid receipt for a withdrawn release remains valid inclusion evidence and still yields rejected or historical policy results. |
| Historical attribution | SCITT can prove registered observation; RFC 3161 can prove an external time bound. Neither creates the release grant or compromise cutoff. |
| Privacy and availability | Optional-by-default evidence avoids an ordinary-release outage dependency. A high-assurance adopter profile may require named services or a quorum, deliberately accepting their privacy and availability costs. |
| Operations and maturity | Standards are sufficient for a disposable fixture and profile now. Production service, witness, retention, exit, and PQ qualification remain later gates. |

Disposition: **later release**, after the TUF decision and a separately accepted
SCITT evidence profile and service-qualification contract.

### C. Deferred optional adapter

This is the production posture for the first release, but it should defer
dependency, not learning. Reserve one namespaced evidence type, use the standard
SCITT media types and RFC 9995/9942 shapes, and add public fixtures to #213. Do
not ship a network client, trust store, default service, or SCITT-conformance
claim until the profile and test evidence exist.

“Optional to the generic protocol” does not force every adopter to ignore it.
A later installed adopter profile may require a named SCITT profile and service
set. In that profile, absent, stale, conflicting, unsupported, or otherwise
unknowable required evidence becomes `indeterminate`; a conclusive
cryptographic or profile violation rejects. A receipt can never upgrade
otherwise insufficient core authority.

Disposition: **first public release**.

### Double signing and wrapping

For any RFC 9943 Transparent Statement, the SCITT statement issuer's COSE_Sign1
signature and the TS's separate COSE_Sign1 receipt are normative. The receipt is
attached to the first object's unprotected header. They authenticate different
actors and different claims.

Placing an already signed OpenPGP object inside, or referring to it from, a
SCITT Signed Statement is merely possible and profile-chosen. RFC 9943 does not
require every pre-signed artifact to be wrapped. RFC 9995 makes the digest form
standard and is the recommended local choice.

Calling the result “double signing the release” is misleading. The OpenPGP
signature authorizes the release under #206/#209. The outer COSE signature
authenticates an evidence issuer's exact-object assertion. The TS receipt proves
VDS inclusion. None should be presented as a second release authorization unless
a future profile deliberately grants and specifies that role.

## Accepted decisions to preserve or reopen

### Preserve the intent

- **#203:** preserve the four-way separation among existence time, signer
  authorization, public observation, and non-equivocation. RFC 9942/9943 confirm
  rather than weaken it. Preserve ordinary release independence from a third
  party.
- **#206:** keep the RFC 9980 certifying-primary/subkey authority for version 1.
  COSE-native authority would be a successor profile, not an in-place encoding
  change.
- **#207:** keep core/profile/adapter/deployment/qualification separation.
  Registration and conformance do not establish qualification authority or
  support.
- **#209:** keep exact JCS/SHA-512/OpenPGP identities, one global current-state
  chain, external-evidence non-authority, archive closure, and the four-result
  pure evaluator.
- **#210:** keep two-channel release-anchor bootstrap, canonical refresh,
  monotonic retained state, trusted-time floor, and current-versus-historical
  behavior. Add SCITT roots and checkpoints as a separate evidence namespace,
  not a replacement state.
- **#204:** keep publication receipts as value-free operational readback and the
  canonical signed pointer as current selector.

### Reopen or refine the mechanism

1. Replace any proposed bespoke “SCITT-like” hash wrapper, receipt object, VDS
   labels, media types, or submission API with RFC 9995, RFC 9942, RFC 9943,
   IANA identifiers, and the eventually published SCRAPI version.
2. Refine #203's “prototype later” posture to **public disposable fixtures now,
   production adapter later**. The standards and official example corpus are
   mature enough to expose binding and result-laundering bugs without choosing a
   service.
3. Settle the already exposed TUF POUF-versus-explicit-security-delta decision
   before the version-1 wire contract freezes. SCITT does not answer it and must
   not become a second current-authority plane.
4. Define qualification authority—issuer or threshold, scope, supersession,
   suspension, and consumer policy—before using SCITT to carry qualification
   records. Logging a record cannot grant its author that role.
5. Preserve #212's explicit prohibition on SCITT receipt validity crossing
   directly to Base Loadout admission, archive, actuation, fitting, or
   release-receipt issuance.

No closed decision needs reopening merely because RFC 9942 and RFC 9943 are now
published. A future choice of architecture A would, however, require explicit
successor decisions for #206, #209, and #210 rather than a silent reinterpretation.

## Release disposition

### First public release

- Keep the JCS/OpenPGP authority and #210 verifier state unchanged.
- Reserve a namespaced SCITT evidence profile and exact registered media types
  without selecting a provider or claiming conformance.
- Fix the bridge subject as exact `signature-envelope/v1` JCS bytes, identified
  in the SCITT Hash Envelope by SHA-512 and its existing media type, with byte
  length cross-checked from the authoritative #209 descriptor.
- Publish the disposable fixture plan below under the conformance lane.
- Keep live collection optional, post-release-capable, and non-authoritative.

### Later release

- Publish a complete SCITT application profile after two independent verifiers
  agree on the positive and negative corpus.
- Add a SCRAPI client only against the final published API or an explicitly
  version-pinned draft experiment.
- Qualify each service, VDS, witness/monitor set, key lifecycle, privacy policy,
  and exit path separately.
- Permit adopter profiles to require a named service set only after that
  qualification and explicit outage semantics exist.
- Add PQ receipt/checkpoint and renewal claims only when every evidence signature
  and historical validation path supports them.

### Deliberate exclusions

- SCITT/COSE-native release authority in version 1.
- A required public TS, CCF VDS profile, monitor, witness, or service trust store.
- Provider discovery, credentials, registration, or receipt retrieval in the
  pure `independent-admission/v1` operation.
- Treating SHA-256 VDS roots as #209 authoritative artifact identity.
- Treating service registration time or RFC 9921 TTC as OpenPGP signing time.
- Importing EAT, CoRIM, RATS attestation authority, SUIT directives, or CCF TEE
  governance into the generic release authority.
- Treating an implementation repository, release, test vector, or first-party
  service statement as conformance certification.

## Smallest useful disposable prototype and fixture corpus

The prototype answers one question: can standard SCITT evidence bind one exact
OpenPGP release object without changing its authority result or causing any
consumer side effect?

### Fixture shape

1. Start with the IETF WG positive and negative receipt vectors.
2. Freeze one disposable #209 `signature-envelope/v1` with exact JCS bytes,
   media type, byte length, and SHA-512 digest. Keep the length in the
   authoritative fixture descriptor; RFC 9995 itself does not define a
   preimage-length header. Use only fixture authority and synthetic content.
3. Create an RFC 9995 COSE Hash Envelope whose inline payload is that raw
   SHA-512 digest. Protect the hash algorithm label 258, preimage content type
   label 259, SCITT `typ`, CWT `iss` and `sub`, algorithm, and key identifier.
   Omit payload location from the authoritative fixture. Use a fresh disposable
   SCITT evidence key, not either RFC 9980 component key.
4. Register the Signed Statement in a disposable TS or build a frozen
   `RFC9162_SHA256` receipt vector. Store the Signed Statement and SCITT receipt
   separately as `.scitt` and `.receipt`; optionally publish a derived
   Transparent Statement whose changing bytes never become release identity.
5. Verify in this order: exact CBOR/profile; trusted TS key and VDS inclusion;
   SCITT statement-issuer signature; RFC 9995 fields; SHA-512 and media-type
   binding; byte length and equality against the frozen #209 descriptor and
   preimage; then the independent #209 OpenPGP, authority-state, release-state,
   and admission checks.
6. Emit the unchanged four-result result with typed evidence diagnostics. Perform
   no network call from pure verification and no install, execution, archive, or
   Base Loadout release-receipt operation.

Use the Microsoft ledger only in its documented virtual/development mode for a
separate SCRAPI interoperability experiment. Pin its exact release and draft
behavior. Its permissive policy and development keys make those results
interop evidence, not service qualification.

### Required negative cases

- one-byte mutation of the JCS preimage;
- wrong SHA-512 digest, authoritative descriptor length, preimage media type,
  `iss`, `sub`, `typ`, or critical profile;
- valid receipt over the wrong entry, invalid inclusion path, unsupported VDS,
  invalid receipt signature, and untrusted or missing retired TS key;
- valid inclusion at two inconsistent retained roots and missing consistency or
  witness evidence;
- valid SCITT evidence over an invalid OpenPGP signature, unauthorized grant,
  stale state, withdrawn release, or incomplete archive;
- a receipt or HTTP `201` treated as `accepted-current`;
- optional evidence absent or invalid versus profile-required evidence absent or
  invalid;
- Transparent Statement bytes substituted for `release-envelope/v1` identity;
- SCITT receipt substituted for a publication receipt or Base Loadout release
  receipt; and
- all three non-current generic outcomes causing zero Base Loadout tuple,
  launcher, installer, archive, and receipt effects.

### Success evidence

The prototype succeeds only when:

- at least two independently implemented verifiers agree on every frozen byte,
  reconstructed root, signature result, and expected failure;
- the SCITT layer never changes the underlying #209 result except that a profile-
  required missing, stale, conflicting, unsupported, or unknowable evidence
  dependency may make an otherwise supportable result `indeterminate`, while a
  conclusive cryptographic or profile violation rejects;
- exact subject bytes remain identical through index, archive, and diagnostic
  output;
- no fixture authority, locator, or key can be accepted by a production profile;
  and
- the run is value-free, offline-verifiable, and has no provider, host, trust-
  store, credential, authenticator, protected-authority, or Base Loadout
  effect.

## Evidence required before conformance or service adoption

### Before claiming object/profile conformance

The claim must name its scope rather than say only “SCITT conformant.” Retain:

- exact RFCs, active-draft revisions, IANA registry snapshot, media types,
  application-profile identifier/version/digest, and supported VDS identifiers;
- deterministic CBOR rules and exact CDDL/profile schemas;
- frozen Signed Statement, receipt, Transparent Statement, RFC 9995 preimage,
  key, inclusion, consistency, and negative vectors;
- proof that protected CWT identity, `typ`, algorithm, hash, and preimage media
  type are enforced and unknown critical semantics fail closed;
- offline verification output from two independent implementations;
- explicit evidence that underlying OpenPGP validation is mandatory and cannot
  be skipped through RFC 9943's receipt-only RP option;
- exact mapping from SCITT evidence failure to the four generic outcomes; and
- separate claims for RFC 9943 object support, RFC 9942/VDS verification,
  RFC 9995 bridging, SCRAPI client behavior, and any service behavior.

### Before adopting or requiring a service

Retain and independently review:

- out-of-band bootstrap for the exact TS identity, receipt keys, algorithms,
  validity, and historical key archive;
- SCITT statement-issuer registration anchors and the complete registration-
  policy history, authentication collateral, and replay procedure;
- exact final or draft-pinned SCRAPI behavior, including asynchronous failure,
  idempotence, readback, rate limiting, and ambiguous-effect reconciliation;
- exact VDS registration and receipt profile, inclusion and consistency
  verification, enumeration/replay access, and retained checkpoints;
- monitor coverage, independently controlled witness or cross-log policy,
  checkpoint exchange, fork test results, and successor-service continuity;
- receipt-key and platform-compromise response, revocation/status policy,
  rollback prohibition or explicit rebootstrap, and tested provider exit;
- statement confidentiality, retained content, metadata correlation, access,
  deletion limits, and privacy review;
- availability and finality objectives, retention/export commitments, outage
  behavior, cost, abuse controls, and shutdown recovery;
- end-to-end algorithm inventory across statement issuer, receipt, VDS hash,
  checkpoints, witnesses, timestamp renewal, and historical verifier;
- independent security assessment, exact deployed source/build identity,
  reproducibility or attestation limits, and current qualification record; and
- a live, non-production acceptance run proving that stored bytes and service
  results match the frozen conformance corpus.

A service receipt alone supplies none of the governance, operation, retention,
or witness evidence above.

## Wayfinder rescope and dependency contracts

The #202 coordinator projected these research consequences into the live map;
this note performs no tracker mutation.

1. **Keep #212 independent of SCITT deployment.** Its accepted consumer profile
   accepts SCITT only through the generic evidence/admission result, binds the
   same exact SHA-512 artifact bytes into the Base Loadout tuple, and allows only
   `accepted-current` to reach the separate tuple gate. Every other result has
   zero launcher, archive, or release-receipt effect.
2. **Give #213 the disposable SCITT bridge corpus.** Inputs are the settled
   #209/#210 contracts, IETF WG vectors, and this profile sketch. Outputs are
   public frozen bytes, expected results, two-verifier interoperability evidence,
   and zero-effect consumer cases. It owns no service selection or production
   key.
3. **Use [Define the generic SCITT evidence profile](https://github.com/nisavid/dotfiles/issues/248).** It owns
   `iss`/`sub` semantics, RFC 9995 exact-byte binding, TS and evidence-issuer
   roots, VDS/profile selection, optional-versus-required policy, result mapping,
   offline bundle, and version transition. It depends on the prototype, not on a
   live provider.
4. **Keep [Qualify a SCITT service integration](https://github.com/nisavid/dotfiles/issues/249) separate.** It depends on the accepted evidence
   profile, a final or pinned API/VDS profile, the qualification-authority
   decision, witness/monitor design, and provider exit evidence. It does not
   block the first public release.
5. **Settle TUF before authority implementation in [Determine TUF conformance and security delta](https://github.com/nisavid/dotfiles/issues/245).** The TUF POUF-versus-explicit-
   delta decision depends on #209/#210 and precedes an authoritative wire freeze.
   The SCITT lane consumes its outcome and never creates a parallel current head.
6. **Keep Base Loadout actuation in its own lane.** [Define the generic consumer
   updater and protected-launcher boundary](https://github.com/nisavid/dotfiles/issues/244)
   owns the protected handoff and updater boundary. #120 retains the protected
   deployment binding, installed identities, and destinations. #121 retains
   complete release-tuple validation, including every required byte-stream
   check. #122 retains create-only archive and terminal release-receipt semantics.

## Uncertainties

- SCRAPI-11 is in the RFC Editor queue and may publish with editorial or
  normative changes. The CCF profile is still in IETF Last Call, and its VDS
  value is not registered.
- No final COSE ML-DSA-65+Ed25519 composite identifier or SCITT hybrid profile
  exists. The active draft's non-repudiation and fresh-key constraints may still
  change.
- The exact SCITT evidence issuer, `iss`/`sub` URI convention, TS trust-root
  distribution, required-service quorum, witness topology, and retention term
  are unsettled.
- No exhaustive public implementation inventory or conformance certification is
  claimed. Public evidence establishes active code and one scoped GA service,
  not a generally qualified adopter service.
- A later receipt profile may use a VDS other than RFC9162_SHA256. Its proof
  properties, privacy model, identifiers, and consistency semantics require a
  fresh analysis rather than name-based equivalence.
- The TUF conformance question remains independent and consequential. This SCITT
  audit does not resolve it.

## Explicit exclusions

This work is planning and public fixtures only. It does not implement a verifier
or service; install software; create or access credentials, authenticators, or
private services; mutate trust stores, providers, hosts, protected authority, or
Base Loadout; perform production signing or verification; alter Agents work;
or create, edit, link, claim, label, resolve, or close an issue.
