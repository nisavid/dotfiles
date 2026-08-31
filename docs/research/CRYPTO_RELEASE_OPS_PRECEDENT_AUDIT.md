# Crypto Ops and Release Ops precedent audit

**Research date:** 2026-08-31

**Status:** Planning research only. This note records a primary-source precedent audit. It is not an accepted decision, an implementation contract, or authority to change a tracker, repository, branch, release, host, provider, credential, key, trust store, protected installation, or Agent Equipment.

## Executive findings

The accepted release-trust design should remain the sole authority and retained-state plane for its first public release. RFC 9580, RFC 9980, and RFC 8785 directly support its chosen OpenPGP composite signature and exact JCS-byte profile. None of the maintained update or supply-chain systems assessed implements the accepted combination of scoped OpenPGP authority, one signed authority-and-release history, provider-neutral publication, offline historical attribution, and a pure four-result evaluator.

That does not make every custom surface equally justified:

1. **TUF is the closest security architecture and the most important unresolved compatibility decision.** TUF permits implementation-defined canonical metadata and signature schemes, so strict JCS, SHA-512, and RFC 9980 OpenPGP do not prevent conformance. The accepted role and client algorithms, however, do not yet demonstrate TUF's root, targets, snapshot, and timestamp workflow. Before the public protocol freezes, choose either a TUF-conformant POUF with named extensions or a non-TUF protocol with an explicit security delta. Do not create both as competing authority planes.
2. **Uptane and SUIT expose the right consumer boundary.** Artifact authenticity is not an instruction to install or run it. A consumer independently checks the exact target, device or execution context, authorization policy, conditions, and actuation result. This strongly supports retaining Agent Equipment's separate tuple gate, candidate-independent launcher, archive, and receipt.
3. **SCITT has matured, but the integration disposition has not changed.** RFC 9942 and RFC 9943 became Proposed Standards in June 2026. They now provide a standards-based receipt and transparency architecture, but not a qualifying witnessed, post-quantum, RFC 9980-compatible public service or authority model. SCITT remains optional evidence, never release authority.
4. **The RFC 3161 choice is sound but needs an explicit profile.** A first-release optional timestamp adapter should cover the exact completed OpenPGP signature bytes, require a strong message imprint and RFC 5816-era certificate identification, retain the TSA policy and validation material, and make no authorization, public-observation, or non-equivocation claim. Long-term evidence requires renewal, such as an RFC 4998 evidence-record strategy, or a deliberate statement that the first release does not promise it.
5. **Build evidence has a standard interchange path.** in-toto Attestation 1.2 and SLSA 1.2 are the best first-release profile for non-authoritative build provenance. DSSE may carry that evidence, and Sigstore bundles may supply optional verification material, but neither envelope can replace the exact OpenPGP signature over the JCS authority objects.
6. **Transport, discovery, and orchestration should stay outside admission.** OCI Distribution and ORAS may carry exact objects; GitHub reusable workflows may orchestrate publication and produce attestations. Registry tags, OCI referrer sets, GitHub environments, OIDC claims, hosted attestations, and provider success do not select current authority.
7. **The generic actuation interface needs evidence before publication.** The first release should contain a fake-actuator contract and hostile fixtures, not a generic privileged installer. RAUC, systemd-sysupdate, Sparkle, and pacman/libalpm demonstrate materially different installation, health, and rollback semantics. They support a common sequence, not yet a proven common public adapter.
8. **Three accepted choices deserve explicit scalability review, not silent generalization:** one certifying primary rather than a threshold root, one default signer for the generic namespace, and one globally serialized state head with human-authorized positive transitions. These are coherent for a single-operator first adopter. TUF and Uptane show the compartmentalization and availability that are traded away. The first release should name that trade; a later multi-operator or high-frequency profile should not inherit it by accident.
9. **Two trusted-client inputs remain underspecified.** “Two independently controlled public channels” needs closed channel classes and control-principal rules, and the claim that a backward clock cannot extend freshness is true only after a trusted time floor exists. These are qualification blockers for the first client, not Agent Equipment-specific policy.
10. **A result document is diagnostics, not a bearer capability.** A protected consumer must select its own anchor, retained trust context, and immutable profile; run or re-run admission over held exact bytes; and bind the admitted bytes through installation readback. Passing caller-supplied result JSON, paths, or digests into a privileged launcher would reintroduce substitution and time-of-check/time-of-use risk.
11. **Qualification evidence needs qualification authority.** The accepted profile model describes exact evidence, reviewers, and lifecycle states, but not the authenticated issuer, scope, threshold, or supersession rules for declaring an implementation or adapter qualified. in-toto, DSSE, Notary, and SCITT can carry a record; none decides who is allowed to issue it.

## Accepted-intent baseline

Accepted decisions are treated here as accurate records of Ivan's intent. The audit tests their external fit; it does not silently replace them.

- [#215, “Define the system threat and authority model”](https://github.com/nisavid/dotfiles/issues/215#issuecomment-5464747293) makes unauthorized acceptance more important than availability, keeps the certifying identity as the cryptographic continuity root, gives DNSSEC only bootstrap and freshness duties, separates logical roles, requires human presence for positive authority, and accepts first-use split-view risk without mandatory witnessed transparency.
- [#206, “Choose the release authority topology and continuity contract”](https://github.com/nisavid/dotfiles/issues/206#issuecomment-5465835347) uses an offline version-6 certifying primary, directly bound version-6 release and status subkeys, RFC 9980 algorithm 30 with SHA-512, scoped grants, routine signer rotation, and predecessor-authorized root transitions.
- [#208, “Choose release-signer custody, recovery, and factor rotation”](https://github.com/nisavid/dotfiles/issues/208#issuecomment-5472198422), [#205, “Research recoverable FIDO authorization for RFC 9980 release signing”](https://github.com/nisavid/dotfiles/issues/205#issuecomment-5463568055), and [#219, “Qualify age-plugin-fido2prf and choose its integration lanes”](https://github.com/nisavid/dotfiles/issues/219#issuecomment-5473754412) keep release and status custody distinct, require local user verification and short-lived plaintext signer exposure, retain post-quantum recovery, and make the selected age and Sequoia builds qualification inputs rather than ambient dependencies.
- [#209, “Define the signed release manifest and independent-admission protocol”](https://github.com/nisavid/dotfiles/issues/209#issuecomment-5474608513) fixes closed JCS object families, SHA-512 object and artifact identity, detached OpenPGP signatures over exact bytes, authority and release state histories, one alternating global state head, and pure <code>independent-admission/v1</code> with exactly <code>accepted-current</code>, <code>attributed-historical</code>, <code>rejected</code>, or <code>indeterminate</code>. Aggregation precedence is conclusive rejection, then unresolved required input, then a mode-appropriate positive result.
- [#210, “Choose client trust bootstrap, refresh, and verification state”](https://github.com/nisavid/dotfiles/issues/210#issuecomment-5474715429) separates anchor initialization, refresh, current verification, and historical verification; binds fingerprint and canonical DNSSEC domain; retains high-water and fork state atomically; and requires the currently trusted verifier and installer to authenticate a successor.
- [#203, “Research historical verification, transparency, and trusted timestamps”](https://github.com/nisavid/dotfiles/issues/203#issuecomment-5463564990) requires signed monotonic history and independent archives, keeps external evidence optional, selects RFC 3161 over the completed OpenPGP signature object as the first adapter, and defers witnessed transparency until an operationally and cryptographically suitable service exists.
- [#204, “Specify the Cloudflare canonical publication and Vercel site boundary”](https://github.com/nisavid/dotfiles/issues/204#issuecomment-5469266482) and [#214, “Research Cloudflare, Vercel, and GitHub publication capabilities”](https://github.com/nisavid/dotfiles/issues/214#issuecomment-5463592296) keep immutable objects and compare-and-swap state canonical at the trust origin while treating presentation sites, mirrors, workflow evidence, and provider receipts as non-authoritative.
- [#207, “Define the reusable core, adapter, and adopter-profile boundary”](https://github.com/nisavid/dotfiles/issues/207#issuecomment-5470521497) chooses one public core, closed versioned contracts, explicit adapters, immutable public profiles, private bindings, no ambient discovery or downgrade, and publication of a seam only after variation and conformance evidence justify it.

The Agent Equipment boundary is also settled in the repository context:

- Generic admission authenticates release bytes and trust state. It does not grant apply, installation, execution, archive, or receipt authority.
- Only <code>accepted-current</code> may reach the Agent Equipment consumer gate. The other three generic outcomes have no actuation, archive, or receipt effects.
- Agent Equipment independently binds its complete execution tuple, a candidate-independent protected launcher, eleven archived byte streams, a create-only archive, and a receipt emitted only after durable archive success.
- The generic verifier/installer and Agent Equipment release-authority assembly remain independently versioned and accepted even if they share one Crypto Ops source project.

[The Agent Equipment context](../agent-equipment/CONTEXT.md), [architecture](../agent-equipment/ARCHITECTURE.md), [implementation handoff](../agent-equipment/IMPLEMENTATION_HANDOFF.md), and [generic component research](../agent-equipment/research/generic-release-trust-components.md) define those boundaries. Open issue [#212, “Specify the Agent Equipment release-authority consumer profile”](https://github.com/nisavid/dotfiles/issues/212) owns their exact mapping.

## Requirements-to-precedents crosswalk

| Requirement | Closest primary precedent | Fit and first-release consequence |
| --- | --- | --- |
| Hybrid post-quantum and classical release signatures | [RFC 9980](https://www.rfc-editor.org/rfc/rfc9980.html) over [RFC 9580](https://www.rfc-editor.org/rfc/rfc9580.html) | Direct adoption. Algorithm 30 is the exact ML-DSA-65+Ed25519 composite selected by the accepted profile; both components must verify. |
| Canonical signed JSON and exact object identity | [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html) and SHA-512 | Direct adoption. Keep exact JCS bytes as the authority surface. Do not add a second CBOR or DSSE interpretation of the same object version. |
| Root continuity, scoped signing roles, rollback and freeze resistance | [TUF 1.0.36](https://theupdateframework.github.io/specification/latest/) | Decide TUF-conformant POUF plus extensions versus explicit non-TUF delta. JCS/OpenPGP can fit; the accepted roles and client algorithm are the unresolved part. |
| Interoperable description of protocol, operations, usage, and format | [TAP 11](https://github.com/theupdateframework/taps/blob/master/tap11.md) | Use its document shape. Call it a TUF POUF only if a working implementation satisfies the TUF role and workflow requirements. |
| Separate artifact trust from device- or consumer-specific installation instruction | [Uptane 2.1.0](https://uptane.org/docs/latest/standard/uptane-standard) | Semantic alignment for the generic-to-Agent Equipment seam. Do not adopt its automotive two-repository protocol. |
| Separate side-effect-free checks from install or invoke directives | [RFC 9019](https://www.rfc-editor.org/rfc/rfc9019.html), [RFC 9124](https://www.rfc-editor.org/rfc/rfc9124.html), and the [SUIT manifest draft](https://datatracker.ietf.org/doc/draft-ietf-suit-manifest/) | Semantic alignment only. Keep command-bearing SUIT manifests and CBOR/COSE outside the authoritative first-release wire format. |
| Pure four-result current and historical admission | No direct standard; TUF client/repository separation is the nearest architecture | Preserve the result algebra. Document how TUF-class failures map to it and prove that external evidence cannot upgrade a result. |
| Trusted existence time | [RFC 3161](https://www.rfc-editor.org/rfc/rfc3161.html), updated by [RFC 5816](https://www.rfc-editor.org/rfc/rfc5816.html) | First optional adapter over the exact completed OpenPGP signature bytes. It is evidence, not authority. |
| Long-term evidence across hash, certificate, or algorithm aging | [RFC 4998](https://www.rfc-editor.org/rfc/rfc4998.html) | Reserve renewal links and retained validation material now; implement later or disclaim a first-release long-term-evidence promise. |
| Generic transparency receipts | [RFC 9942](https://www.rfc-editor.org/rfc/rfc9942.html) and [RFC 9943](https://www.rfc-editor.org/rfc/rfc9943.html) | Later optional SCITT adapter. The standards are mature enough; the missing pieces are a profile, witnessed service, retained roots, and compatible PQ path. |
| Append-only and split-view evidence | [RFC 9162](https://www.rfc-editor.org/rfc/rfc9162.html) and [Sigsum](https://www.sigsum.org/docs/) | Reference or optional evidence only. Inclusion without monitoring, gossip, or witnesses is not global non-equivocation. |
| Build provenance | [in-toto Attestation 1.2](https://github.com/in-toto/attestation/blob/main/spec/v1/README.md) and [SLSA 1.2](https://slsa.dev/spec/v1.2/build-provenance) | First optional evidence profile, exact-digest-bound and non-authoritative. |
| Evidence envelope and payload-type domain separation | [DSSE 1.0.2](https://github.com/secure-systems-lab/dsse/blob/master/protocol.md) | Use within external evidence and as a conformance lesson. Deliberately incompatible with the authoritative OpenPGP-over-exact-JCS envelope. |
| Evidence bundles and hosted verification roots | [Sigstore bundle and trust-root models](https://github.com/sigstore/protobuf-specs) | Optional evidence adapter. Fulcio, Rekor, TSA, CT, and OIDC identities remain separate trust inputs, never release authority. |
| Artifact transport and related-object discovery | [OCI Distribution 1.1](https://github.com/opencontainers/distribution-spec/blob/main/spec.md) and [ORAS](https://github.com/oras-project/oras) | Later transport adapter. Fetch by exact descriptor, recompute authoritative SHA-512, and never select authority from tags or referrer enumeration. |
| Protected actuation, health, and rollback | [RAUC](https://github.com/rauc/rauc), [systemd-sysupdate](https://github.com/systemd/systemd/blob/main/man/systemd-sysupdate.xml), [Sparkle](https://sparkle-project.org/documentation/security-and-reliability/), and [pacman/libalpm](https://man.archlinux.org/man/libalpm.3.en) | Extract a fake-actuator sequence now; defer real adapters until independent qualification proves exact-byte handoff and consumer-owned health. |

## Candidate analysis

### TUF: decide conformance before freezing the role and state model

**Maturity.** TUF is a maintained project specification. The [current published specification](https://theupdateframework.github.io/specification/latest/) identifies version 1.0.36, dated 2026-08-05. It defines four top-level roles, threshold signatures, sequential root updates, metadata version and expiration checks, consistent snapshots, and a detailed client workflow intended to resist arbitrary installation, rollback, freeze, fast-forward, and mix-and-match attacks. It deliberately leaves implementation formats and signing schemes open when a POUF defines them unambiguously. [TUF source specification](https://github.com/theupdateframework/specification/blob/master/tuf-spec.md)

[TAP 11](https://github.com/theupdateframework/taps/blob/master/tap11.md) is accepted and defines a POUF as the interoperable protocol, operations, usage, and format description for a working TUF implementation. TUF maintainers do not certify a POUF's security or accuracy. [TAP 21](https://github.com/theupdateframework/taps/blob/master/tap21.md), dated 2026-04-30, is still a draft. It proposes pure ML-DSA with a TUF-specific SHA-512 prehash and domain separator; it is not the RFC 9980 hybrid OpenPGP profile.

**Requirement addressed.** Root and signer compromise resilience, delegated authority, freshness, rollback and freeze detection, coherent snapshots, exact target selection, client/repository separation, and interoperability documentation.

**Current conformance assessment.** The selected JCS, SHA-512, and RFC 9980 signature scheme can be defined in a TUF POUF. They are not a reason to reject TUF. The accepted objects and client algorithm do not yet establish conformance:

| TUF requirement | Nearest accepted construct | Remaining mismatch or proof obligation |
| --- | --- | --- |
| Root metadata names root, targets, snapshot, and timestamp keys and thresholds; root N+1 is verified by both the old and new root thresholds | Certifying primary, root transition, authority grant, and authority state | Closed schemas do not presently define the four TUF role thresholds or TUF root metadata. One certifying key and OpenPGP succession preserve continuity but are not, by themselves, the TUF root algorithm. |
| Targets metadata signs target paths, lengths, hashes, delegation, version, and expiration | Release manifest, release envelope, grants, and release state | Artifact identity and scope are strong, but the manifest deliberately has no acceptance expiry and the closed family is not identified as TUF targets metadata. A POUF cannot omit security-relevant TUF fields merely by encoding equivalent information elsewhere without proving the client algorithm remains TUF. |
| Snapshot metadata commits the coherent versions of targets metadata | Alternating global head and complete stream map | Both prevent mix-and-match, but the accepted chain couples authority and release events and uses digests/generations rather than the specified snapshot workflow. A field and state-transition proof is required. |
| Timestamp metadata provides a short-lived signed view of the current snapshot under a minimally trusted online role | Canonical newest state object, signed freshness, and human-authorized <code>reaffirm</code> | The accepted system deliberately avoids an online positive-authority key. That may be stronger in compromise resistance and weaker in availability, but it is a different role and refresh algorithm. |
| Client fetches and verifies root, timestamp, snapshot, targets, and exact target bytes in a defined order | Canonical pointer retrieval, complete signed graph refresh, atomic retained state, and pure independent admission | The separation is compatible in spirit, but the acquisition order, metadata types, and result meanings differ. Historical attribution and the four-result algebra can be extensions; they do not substitute for the TUF refresh checks. |

This assessment cannot honestly claim current TUF conformance. It also cannot conclude that conformance is impractical without the field-by-field exercise.

**Disposition.** Before the first public protocol release, Crypto Ops should choose between:

1. **TUF-conformant custom POUF plus named extensions:** preserve JCS, SHA-512, RFC 9980, historical evidence, and four-result consumer output while adopting the required TUF roles and client workflow; or
2. **Explicit non-TUF protocol:** keep the accepted role and global-state model, publish the exact TUF delta and equivalent proof obligations, and never use “TUF-compatible” to imply conformance.

Do not deploy a TUF repository beside the custom history as a second authority plane. A transport-only TUF adapter remains a later option.

**Benefits.** TUF supplies the strongest established vocabulary and fixture source for update-security failure modes. Its division between repository metadata, a trusted client, and the application that decides what to do with an authenticated target supports the accepted pure-admission boundary. Its root, targets, snapshot, and timestamp roles also make key-compromise blast radius and online-freshness duties explicit.

**Conflicts and boundaries.**

- The accepted protocol has closed authority, release, envelope, state-index, archive, and evidence object families rather than an established mapping to TUF root, targets, snapshot, and timestamp metadata.
- One alternating global head and separately retained historical attribution are not TUF's repository workflow. TUF metadata expires and is aimed at obtaining current trusted targets; <code>attributed-historical</code> is an additional local protocol meaning.
- The accepted authority uses OpenPGP v6 certification and RFC 9980 algorithm 30. TUF permits that implementation-defined scheme through a POUF; the draft PQ TAP is a different optional pure-ML-DSA proposal, not a blocker.
- TUF's high-level updater refreshes, selects, and downloads. The accepted evaluator performs no I/O or mutable selection. A TUF-shaped fetch layer must remain outside <code>independent-admission/v1</code>.
- A single certifying primary and one default signer do not provide TUF's recommended threshold-root and role-compartmentalization resilience. That may be an intentional single-operator profile, but it must not be presented as equivalent.

**Migration cost.** Low for the conformance/delta study and invariant fixtures; medium if existing closed objects can carry all TUF-required fields without changing accepted identity; high and wire-breaking if root, targets, snapshot, timestamp, bootstrap, archive, and client workflow must be restructured. The cost is lowest before any public wire contract ships, which is why the decision should precede #213.

### Uptane: align the consumer seam, do not adopt the automotive protocol

**Maturity.** Uptane 2.1.0 is a current Joint Development Foundation standard for ground-vehicle update systems. It permits multiple encodings but requires two independently trusted repository roles: an Image repository authenticates images, while a Director uses inventory to instruct an exact ECU which image to install. Full verification compares the repositories' metadata. Uptane also defines POUFs for interoperable implementation choices. [Uptane Standard 2.1.0](https://uptane.org/docs/latest/standard/uptane-standard)

**Requirement addressed.** Separation of generic artifact authenticity from a consumer-specific, exact-target installation decision; compromise containment; secure time; rollback and mix-and-match resistance.

**Disposition.** Release Ops and Agent Equipment should **align semantically** with the Image/Director separation without claiming Uptane conformance. The generic release system authenticates exact bytes and current state; Agent Equipment independently supplies the equivalent of target inventory, execution tuple, apply authority, health, archive, and receipt rules.

**Benefits.** Uptane demonstrates that two valid signatures can answer different questions: “is this an authentic image?” and “is this the image this exact consumer should install now?” It also demonstrates the value of keeping download, verification, installation, and post-installation state distinct.

**Conflicts and boundaries.** Its vehicle, ECU, inventory, two-repository, secure-time, and metadata-role assumptions are not provider-neutral generic release semantics. A Director-like service would create an additional online authority plane and could collide with Agent Equipment's separately issued apply authorization. Uptane's native wire and cryptographic profiles do not provide the accepted OpenPGP algorithm-30 or pure four-result interface.

**Migration cost.** Low to adopt the semantic split and fixtures; high to adopt the protocol or operate Director and Image repositories.

### IETF SUIT: align conditions and effects; defer the command format

**Maturity.** [RFC 9019](https://www.rfc-editor.org/rfc/rfc9019.html) defines the SUIT architecture, and [RFC 9124](https://www.rfc-editor.org/rfc/rfc9124.html) defines its information model; both are Informational RFCs. As of the research date, the [SUIT working-group documents](https://datatracker.ietf.org/wg/suit/documents/) show the manifest and related update-management documents as Internet-Drafts progressing through the RFC Editor or IESG process, not published RFC wire standards. The manifest draft uses CBOR and COSE and distinguishes side-effect-free conditions from side-effecting directives. [SUIT manifest draft](https://datatracker.ietf.org/doc/draft-ietf-suit-manifest/)

**Requirement addressed.** Trust-domain authorization, exact component targeting, dependencies, monotonic sequence, preconditions, safe processing order, installation, and invocation.

**Disposition.** Crypto Ops should **align semantically** with SUIT's separation between conditions and directives. Agent Equipment conditions remain in the pure consumer gate; directives remain in the candidate-independent actuator. SUIT's command-bearing manifest should be **deferred** as a constrained-device adapter and deliberately excluded from the authoritative first-release wire format.

**Benefits.** SUIT treats an update as authorized remote code execution and therefore makes preauthorization, dependencies, install conditions, and invoke authority explicit. That is useful pressure against letting a signed release manifest silently become an execution plan.

**Conflicts and boundaries.** The accepted release manifest is descriptive and pure admission has no side effects. A SUIT directive sequence inside the authority object would give candidate-supplied signed data more influence over execution and would blur Agent Equipment's independent tuple and apply-authority boundary. CBOR/COSE would also introduce a second canonicalization and signature stack while the manifest wire standard remains unfinished.

**Migration cost.** Low for semantic and test alignment; high and wire-breaking for direct manifest adoption.

### OpenPGP and JCS: adopt directly and keep implementation qualification explicit

**Maturity.** [RFC 9580](https://www.rfc-editor.org/rfc/rfc9580.html) is the current OpenPGP Proposed Standard. [RFC 9980](https://www.rfc-editor.org/rfc/rfc9980.html), published in June 2026, standardizes ML-KEM, ML-DSA, and SLH-DSA for OpenPGP; algorithm 30 is the required ML-DSA-65+Ed25519 composite. [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html) defines JCS. Sequoia's maintained source reports RFC 9580 and RFC 9980 support. Its latest listed releases are [sequoia-openpgp 2.4.1](https://gitlab.com/sequoia-pgp/sequoia/-/tags), dated 2026-07-09, and [sq 1.4.0](https://gitlab.com/sequoia-pgp/sequoia-sq/-/tags), dated 2026-07-07; the project also maintains an [OpenPGP interoperability test suite](https://gitlab.com/sequoia-pgp/openpgp-interoperability-test-suite).

**Requirement addressed.** Hybrid post-quantum release signatures, certification lineage, detached exact-byte signatures, stable canonical representation, and offline verification.

**Disposition.** **Adopt directly in the first public release.** Keep the accepted packet, component, issuer, hash, signature-type, binding, and projection checks. Qualify exact implementations and cryptographic backends rather than treating standards conformance as proof that every available build is suitable.

**Benefits.** This is no longer a private composite construction. It has a standards-track algorithm identifier, specified encoding, and a maintained implementation path. OpenPGP certification and revocation also match the accepted certifying-primary and subkey topology better than X.509-, COSE-, or DSSE-based replacements.

**Conflicts and boundaries.** Ecosystem breadth remains narrower than classical OpenPGP. RFC 9980 standardization does not establish hardware, provider, FIDO, recovery, or backend qualification. It also does not provide release-state semantics, trusted time, transparency, or consumer authority.

**Migration cost.** Already accepted. Future implementation substitution is medium risk because packet and backend behavior must be requalified even when the algorithm name matches.

### CBOR, COSE, and post-quantum COSE: expose adapters, not dual authority encodings

**Maturity.** [RFC 8949](https://www.rfc-editor.org/rfc/rfc8949.html) makes CBOR an Internet Standard and defines deterministic encoding rules, while noting that CBOR itself does not impose one universal canonical form. [RFC 9052](https://www.rfc-editor.org/rfc/rfc9052.html) and [RFC 9053](https://www.rfc-editor.org/rfc/rfc9053.html) make COSE an Internet Standard. [RFC 9964](https://www.rfc-editor.org/rfc/rfc9964.html), published in June 2026, defines pure ML-DSA for JOSE and COSE. The [composite-signature draft](https://datatracker.ietf.org/doc/draft-ietf-jose-pq-composite-sigs/) is still an Internet-Draft and its algorithm identifiers remain subject to change.

**Requirement addressed.** Compact deterministic data, store-and-forward signatures, detached payloads, and interoperation with SUIT and SCITT.

**Disposition.** Keep JCS plus OpenPGP as the only authoritative first-release encoding. **Expose a later evidence or transport adapter** for COSE-based ecosystems. Any future authority encoding needs a new closed object-family version and an explicit transition; the same object version must never admit both JSON/OpenPGP and CBOR/COSE interpretations.

**Benefits.** CBOR/COSE is mature and compact and is the native ecosystem for SUIT and SCITT. Detached content and application profiles can support offline evidence.

**Conflicts and boundaries.** RFC 9964 is pure ML-DSA, not the accepted composite. The composite work remains a draft. Adopting COSE now would duplicate key representation, canonicalization, signature inputs, algorithm policy, and conformance burden without replacing the OpenPGP authority lineage.

**Migration cost.** Low for opaque evidence carriage, medium for a verified evidence adapter, and high/wire-breaking for authority migration.

### SCITT and COSE receipts: later optional evidence

**Maturity.** [RFC 9943](https://www.rfc-editor.org/rfc/rfc9943.html) defines the SCITT architecture as a Proposed Standard, and [RFC 9942](https://www.rfc-editor.org/rfc/rfc9942.html) defines COSE receipts for verifiable data structures as a Proposed Standard. Both were published in June 2026. The [SCITT working-group page](https://datatracker.ietf.org/wg/scitt/documents/) still lists the reference API and implementation profiles as drafts at different stages.

**Requirement addressed.** Registration of signed statements, offline-verifiable inclusion and consistency receipts, independently operated transparency services, and evidence portability.

**Disposition.** **Use only as optional external evidence, later.** Reserve a typed SCITT receipt profile that commits the exact OpenPGP release-signature bytes or their unambiguous strong digest. Do not wrap or replace the authority object merely to call it a SCITT Signed Statement. Prototype an adapter only when the selected API/profile, service trust roots, witness policy, retention, and PQ migration path are qualified.

**Benefits.** SCITT is the closest neutral standards path for receipts over arbitrary signed statements. It can carry inclusion and consistency evidence without requiring the verifier to contact the service at verification time.

**Conflicts and boundaries.** Registration proves neither that a statement is true nor that its signer had release authority. Service ordering is not necessarily release issuance order. SCITT's native statements are COSE, and a receipt still needs independently trusted service keys, monitors or witnesses, retained checkpoints, and a privacy decision. A receipt cannot upgrade <code>rejected</code>, <code>indeterminate</code>, or <code>attributed-historical</code> to <code>accepted-current</code>.

**Migration cost.** Low for the generic evidence slot, medium for a read-only adapter and retained validation bundle, high for making SCITT a required release service or authority plane.

### RFC 3161, RFC 5816, and RFC 4998: profile now; renew later

**Maturity.** [RFC 3161](https://www.rfc-editor.org/rfc/rfc3161.html) is the established Time-Stamp Protocol. [RFC 5816](https://www.rfc-editor.org/rfc/rfc5816.html) updates its certificate identification for modern hashes. [RFC 4998](https://www.rfc-editor.org/rfc/rfc4998.html) defines Evidence Record Syntax for renewing timestamp and hash-tree evidence before algorithms, keys, or certificates age out. [RFC 9921](https://www.rfc-editor.org/rfc/rfc9921.html) provides the analogous COSE timestamp-header distinction between timestamping content and timestamping a completed signature.

**Requirement addressed.** Evidence that exact signature bytes existed no later than an external authority's asserted time, plus optional long-term renewal.

**Disposition.** **Adopt an optional RFC 3161 profile in the first public release.** It should specify the exact completed OpenPGP signature bytes as the subject, a SHA-512 message imprint unless a successor profile says otherwise, nonce and policy handling, RFC 5816-compatible certificate identification, and retention of TSA certificates, chain, policy, revocation or validation material, and original response bytes. **Defer RFC 4998 renewal execution** while reserving typed renewal and supersession links.

**Benefits.** The adapter can bound existence before a later-discovered compromise cutoff without altering release identity or requiring a public log. It is offline-verifiable if the complete validation bundle is retained.

**Conflicts and boundaries.** A TSA knows time, not OpenPGP scope or authority. It does not prove publication or non-equivocation. Common TSA deployments remain classical, so the evidence is not post-quantum end to end. Mandatory collection would add release-time availability, privacy, and third-party trust dependencies.

**Migration cost.** Low before issuance when the evidence model is already typed; medium to retrofit archived signatures and validation material; high or impossible to manufacture credible historical evidence after the relevant time.

### Certificate Transparency and Sigsum: reference append-only properties; do not require either

**Maturity.** [RFC 9162](https://www.rfc-editor.org/rfc/rfc9162.html) is the Experimental Certificate Transparency v2 RFC. It specifies Merkle inclusion and consistency proofs for public TLS certificates and requires monitoring or equivalent cross-checking to address bad entries and split views. It is not a generic release-log standard.

Sigsum is a maintained transparency project for signing-key usage, not a standards-body specification. Its documentation labels the log-server protocol and witness-cosignature format stable v1, the witness-cosigning protocol a release candidate, and the proof-bundle and trust-policy formats works in progress. It uses Ed25519 and SHA-256 and has operating logs and witnesses, but not the accepted RFC 9980 composite authority. [Sigsum documentation](https://www.sigsum.org/docs/), [services](https://www.sigsum.org/services/), and [design](https://www.sigsum.org/)

**Requirement addressed.** Append-only observation, inclusion and consistency proofs, witnessed checkpoints, offline proof verification, and detection of unauthorized signer use.

**Disposition.** **Use RFC 9162 only as a proof-structure reference or through a SCITT receipt profile.** **Defer Sigsum to an optional evidence adapter** if its stable formats, witness policy, service commitments, and PQ agility later meet an adopter's needs. Neither belongs in the required first-release path.

**Benefits.** Sigsum's witnessed-checkpoint model addresses the split-view weakness of a lone inclusion receipt more directly than publisher archives. Offline proofs and monitors can expose unexpected key use.

**Conflicts and boundaries.** CT is certificate-specific and Experimental. Sigsum adds a separate Ed25519 signing identity and SHA-256 statement format, while its trust-policy and proof-bundle formats are not yet stable. Both require log and witness discovery, monitoring, durable checkpoint retention, and an operator policy. Neither knows the accepted authority graph or four-result semantics.

**Migration cost.** Low for a generic opaque evidence slot; medium to operate a monitor and retain witnessed proofs; high to make the log a required dependency or replace the authority history.

### DSSE, in-toto, and SLSA: standardize evidence, not authority

**Maturity.** [DSSE 1.0.2](https://github.com/secure-systems-lab/dsse/blob/master/protocol.md) is a maintained community specification. It signs a pre-authentication encoding of payload type and exact payload bytes. Its key identifier is an unauthenticated verification hint; DSSE does not define key management, identity, policy, or canonicalization. [in-toto Attestation 1.2](https://github.com/in-toto/attestation/blob/main/spec/v1/README.md) uses an envelope, a digest-identified subject-bearing Statement, and a typed predicate. [SLSA 1.2](https://slsa.dev/spec/v1.2/) defines current provenance and verification expectations.

**Requirement addressed.** Build and source provenance, typed external claims, exact subject digests, payload-type domain separation, and policy-engine input.

**Disposition.** **Adopt in-toto Attestation 1.2 plus SLSA 1.2 as the first optional build-evidence profile** when a Release Ops producer exists. DSSE is permitted inside that evidence. **Document deliberate incompatibility** with the authority envelope: the accepted OpenPGP signature covers the exact JCS object, not DSSE's pre-authentication encoding.

**Benefits.** This avoids inventing a build-provenance schema and permits evidence from maintained CI ecosystems. SLSA makes the builder identity and build parameters explicit policy inputs. DSSE's domain separation also supplies useful cross-object substitution tests.

**Conflicts and boundaries.** Provenance describes how bytes were built; it does not make them an authorized current release. A DSSE or SLSA verifier has its own identities and policy. External SHA-256 subject digests must be correlated to the exact bytes whose authoritative SHA-512 identity appears in the signed release graph. Missing or invalid optional evidence may affect only a profile that explicitly requires it; it cannot repair a core failure.

**Migration cost.** Low for producer-generated evidence and opaque retention; medium for a qualified verifier profile; high and unnecessary for replacing the authority envelope.

### Sigstore and Notary: optional ecosystem adapters

**Maturity.** Sigstore is a maintained implementation ecosystem. Its [bundle model](https://github.com/sigstore/protobuf-specs/blob/main/protos/sigstore_bundle.proto) carries signatures and verification material, while its [trusted-root model](https://github.com/sigstore/protobuf-specs/blob/main/protos/sigstore_trustroot.proto) separately represents certificate authorities, transparency logs, CT logs, timestamp authorities, operators, and validity periods. Sigstore distributes public-good roots with [TUF](https://github.com/sigstore/root-signing).

[Notary Project specifications 1.1](https://github.com/notaryproject/specifications/releases) are the maintained specification set implemented by Notation for signing OCI descriptors. The [signature specification](https://github.com/notaryproject/specifications/blob/main/specs/signature-specification.md) and [trust-store and trust-policy model](https://github.com/notaryproject/specifications/blob/main/specs/trust-store-trust-policy.md) use JWS or COSE, X.509 identities, and OCI artifact discovery.

**Requirement addressed.** Verification bundles, hosted identity and transparency evidence, OCI signature discovery, and interoperability with existing artifact ecosystems.

**Disposition.** **Expose optional read-only evidence adapters.** A Sigstore adapter may validate in-toto/SLSA evidence and retain a self-contained bundle. A Notation adapter may report an independently evaluated OCI signature. Neither result maps directly to <code>accepted-current</code>. Notation belongs later unless a real OCI adopter requires it.

**Benefits.** Both ecosystems reduce bespoke parsing and make their own trust inputs explicit. Sigstore bundles support offline verification when roots and material are retained. Notation provides a standard way to discover signatures attached to OCI descriptors.

**Conflicts and boundaries.** Fulcio OIDC identities, X.509 chains, Rekor or CT inclusion, TSA evidence, JWS/COSE envelopes, and Notation trust-policy modes are separate trust planes. Current public roots and common algorithms do not implement the accepted RFC 9980 authority. Provider root refresh is I/O outside pure admission, and a stale adapter root makes that evidence unavailable or indeterminate rather than changing core authority.

**Migration cost.** Medium for each qualified evidence adapter; high for replacing the OpenPGP authority or making a hosted service mandatory.

### OCI Distribution and ORAS: exact-object transport only

**Maturity.** OCI Image and Distribution 1.1 standardized artifact manifests and a referrers API. Registries may still use a fallback tag schema when the API is unavailable. [OCI 1.1 announcement](https://opencontainers.org/posts/blog/2024-03-13-image-and-distribution-1-1/) and [Distribution specification](https://github.com/opencontainers/distribution-spec/blob/main/spec.md). [ORAS](https://github.com/oras-project/oras) is a maintained client and library for pushing, pulling, copying, and discovering OCI artifacts and layouts.

**Requirement addressed.** Distribution, immutable-object addressing, copying, related-evidence discovery, and ecosystem tooling.

**Disposition.** **Use only as optional transport and discovery, later.** An adapter should resolve an exact descriptor, retrieve exact bytes, validate the transport digest, and then recompute the protocol's authoritative SHA-512 identity. Tags and referrer lists are never current-state selectors.

**Benefits.** OCI registries and layouts can carry release objects, artifacts, and evidence without a bespoke blob service. ORAS supplies maintained tooling for exact digest retrieval and copying.

**Conflicts and boundaries.** OCI commonly identifies content with SHA-256, while the accepted protocol uses SHA-512. A registry's mutable tags, garbage collection, referrer enumeration, authentication, and availability are provider behavior, not signed authority state. OCI signatures do not prove Agent Equipment admission or actuation.

**Migration cost.** Low to transport opaque blobs, medium to qualify registry capability and retention, high if existing publication is redefined around registry state.

### GitHub, reproducible builds, and BOMs: optional orchestration and evidence

**Maturity.** GitHub's official documentation states that artifact attestations use Sigstore and SLSA, and that an attestation is not by itself a security guarantee. Reusable workflows and OIDC expose exact workflow identity claims, while environments add operator-controlled deployment gates. [Artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations), [offline verification](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline), [OIDC](https://docs.github.com/en/actions/reference/security/oidc), and [deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)

[Reproducible Builds](https://reproducible-builds.org/docs/definition/) defines bit-for-bit reproducibility and the [SOURCE_DATE_EPOCH convention](https://reproducible-builds.org/specs/source-date-epoch/). [SPDX 3.0.1](https://spdx.github.io/spdx-spec/) and [CycloneDX 1.7](https://github.com/CycloneDX/specification) are maintained BOM models.

**Requirement addressed.** Repeatable release operations, short-lived publication credentials, build provenance, independent rebuild evidence, and dependency inventory.

**Disposition.** Release Ops may **use a full-commit-pinned reusable workflow as optional first-release orchestration** and emit in-toto/SLSA evidence. Reproducibility should be a qualification target. Preserve one qualified SPDX or CycloneDX output as exact-digest-bound evidence when a producer exists; do not put either parser in independent admission or require both.

**Benefits.** This uses maintained CI and evidence standards without giving the provider authority. Reproducibility and independent rebuilds can expose hidden build inputs. BOMs provide portable inventory for later policy.

**Conflicts and boundaries.** GitHub environment approval is an orchestration gate, not the local FIDO-backed release-signing authorization. OIDC, workflow identity, hosted attestations, and provider roots are external evidence. Reproducibility does not prove source authenticity or release authority. BOM completeness and parser safety are independent qualification concerns.

**Migration cost.** Low for a pinned workflow and evidence retention; medium for offline root material and predicate verification; high if CI is made mandatory for signing or current-state selection.

### RAUC, systemd-sysupdate, Sparkle, and pacman: learn one sequence, defer real adapters

**Maturity and fit.**

- [RAUC](https://github.com/rauc/rauc) is a maintained embedded-Linux updater with signed bundles, A/B slots, boot-attempt fallback, and consumer-controlled <code>mark-good</code>/<code>mark-bad</code> behavior. It is the closest maintained precedent for separating install, boot attempt, health confirmation, and rollback.
- [systemd-sysupdate](https://github.com/systemd/systemd/blob/main/man/systemd-sysupdate.xml) remains documented as experimental. Its native remote source uses SHA256SUMS plus OpenPGP, local sources do not receive equivalent authentication, and activation across multiple transfers is not atomic.
- [Sparkle](https://sparkle-project.org/documentation/security-and-reliability/) is a maintained macOS application updater with EdDSA appcast signatures, Apple code-signing checks, staged helpers, and atomic replacement, but it is integrated with candidate-controlled application policy.
- [pacman and libalpm](https://man.archlinux.org/man/libalpm.3.en) provide a maintained exact-local-package transaction path, signature policy, database state, and readback surfaces, while package scriptlets execute candidate code and native keyring results remain a separate trust plane.

**Requirement addressed.** Protected installation, exact-byte actuation, activation, readback, application health, commit, rollback, and local transaction evidence.

**Disposition.** Define only this first-release sequence:

1. prepare the exact bytes already admitted as current;
2. independently validate the consumer tuple;
3. invoke a protected actuator that cannot reselect the candidate;
4. read back immutable installed identity and state;
5. let the consumer decide health;
6. commit or roll back;
7. archive and issue any receipt under the consumer's own rules.

Ship fake-actuator fixtures for crash, retry, partial mutation, digest mismatch, health failure, rollback failure, and receipt binding. **Defer every real platform adapter.**

**Benefits.** The sequence is common across the assessed systems while preserving their different platform mechanics. Fake adapters can prove that the three non-current generic outcomes and every consumer-gate failure produce zero privileged effects.

**Conflicts and boundaries.** Native signature checks, version selection, updater services, app delegates, package keyrings, and “mark good” results cannot replace the generic gate. Agent Equipment's receipt means durable closure over its exact eleven streams; no installer exit code has that meaning.

**Migration cost.** Low for the fake contract, medium to high per real platform, and high for any attempt to publish one generic privileged installer before two implementations prove the seam.

## First-public-release and later disposition

### Resolve before the related public surface

- Before the protocol wire and #213 corpus freeze, choose “TUF-conformant custom POUF plus named extensions” or “explicit non-TUF protocol with a complete delta.” Do not freeze the twelve closed families and then discover whether TUF fields can be added without breaking object identity.
- Before any public adapter is called “qualified,” define the authenticated qualification issuer, role, scope, threshold, predecessor, suspension, supersession, and installed trust policy.
- Before the first qualified client release, define bootstrap channel classes, distinct control principals, conflict behavior, and the first trusted-time observation. Narrow the backward-clock claim to the period after a protected floor exists unless initial trusted time is provisioned or attested.
- Before any public actuation surface, define the protected byte handoff. A serialized admission result, caller path, or caller digest is never an actuation capability.

### Include in the first public release

- RFC 9580/9980 OpenPGP and RFC 8785 JCS as the only authority encoding.
- The pure four-result evaluator and separately modeled bootstrap, refresh, current, and historical operations.
- The output of the TUF decision: either a conformant POUF and its extensions or a non-TUF security-invariant, failure-mapping, and delta document. Both routes need hostile fixtures for root transition, rollback, freeze, fast-forward, mix-and-match, length/digest mismatch, consistent retrieval, and trusted-state crash recovery.
- A public protocol/operations/usage/format document shaped by TAP 11. Its conformance label must match the chosen role and client algorithm, not merely its JSON and signature encoding.
- A typed external-evidence interface that cannot affect core authority precedence.
- An optional RFC 3161 exact-signature profile with RFC 5816-era certificate identification and self-contained validation material.
- An in-toto Attestation 1.2 and SLSA 1.2 profile when Release Ops has a real producer. DSSE may carry that evidence.
- Exact cross-digest binding for evidence and transports that identify bytes with SHA-256 while the authority graph identifies them with SHA-512.
- A SHA-pinned GitHub reusable workflow only if it is the selected orchestration adapter; its environments, OIDC claims, attestations, and receipts remain evidence.
- A fake consumer actuator and negative fixtures. No platform mutation is implied.
- A protected-consumer request shape in which the launcher selects its own anchor, trust context, and immutable profile; verifies exact held bytes; binds the admitted state heads and request to those bytes; and rehashes installed bytes before health, archive, or receipt decisions. Result JSON remains diagnostics.

### Defer until after first-release evidence

- If the explicit non-TUF route is selected, any later TUF wire/repository adapter or TUF-conformant profile. If the conformant route is selected, do not add a duplicate TUF authority plane.
- SCITT receipt verification and service submission.
- Sigsum, Sigstore, Rekor, Notation, OCI/ORAS, or other hosted evidence and transport adapters not demanded by a real adopter.
- RFC 4998 renewal automation.
- SUIT/COSE constrained-device profiles and any COSE composite authority work.
- RAUC, systemd-sysupdate, Sparkle, pacman/libalpm, or other real platform actuators.
- Multi-operator threshold-root, multi-signer, sharded-state, or high-frequency release profiles.

### Deliberately exclude from the authoritative path

- A second JWS, COSE, DSSE, Sigstore, Notation, package-manager, or provider signature result for the same authority-object version.
- Mutable tags, referrer sets, release pages, workflow outcomes, environment approvals, timestamps, transparency receipts, and mirror observations as current-state selectors.
- Candidate-selected profiles, anchors, origins, adapters, destinations, entry points, health rules, or receipt meanings.
- Any mapping that upgrades external evidence success to <code>accepted-current</code>.

## Decision-impact audit

### Accepted decisions

| Decision | Audit impact |
| --- | --- |
| [#203, “Research historical verification, transparency, and trusted timestamps”](https://github.com/nisavid/dotfiles/issues/203#issuecomment-5463564990) | Uphold the optional-adapter disposition. SCITT's standards are now published, but the accepted decision already distinguishes standards maturity from a suitable witnessed service. Refine the RFC 3161 adapter contract with RFC 5816 certificate identification, retained validation material, and an explicit RFC 4998 renewal or no-long-term-promise choice. |
| [#204, “Specify the Cloudflare canonical publication and Vercel site boundary”](https://github.com/nisavid/dotfiles/issues/204#issuecomment-5469266482) | Uphold. OCI/ORAS, SCITT, Sigstore, and GitHub can be adapters or evidence stores only. Their mutable discovery state cannot replace the signed compare-and-swap head. |
| [#205, “Research recoverable FIDO authorization for RFC 9980 release signing”](https://github.com/nisavid/dotfiles/issues/205#issuecomment-5463568055) | No standards-driven change. TUF TAP 21's HSM message-size concerns do not turn FIDO user verification or age-envelope unwrap into an independent release-intent display or signer. |
| [#206, “Choose the release authority topology and continuity contract”](https://github.com/nisavid/dotfiles/issues/206#issuecomment-5465835347) | Keep the RFC 9980 subkey topology for the first adopter. Reconsider whether “one default signer serves the adopter's generic release namespace” and a single certifying primary are generic defaults or a named single-operator profile. TUF's threshold root and delegated targets roles make the sacrificed compromise isolation explicit. |
| [#207, “Define the reusable core, adapter, and adopter-profile boundary”](https://github.com/nisavid/dotfiles/issues/207#issuecomment-5470521497) | Uphold its separation rule. Add a decision for qualification authority: exact evidence and a named reviewer are not self-authenticating. Before any adapter is “qualified,” define which key or role can issue, suspend, supersede, or retire a qualification for which subject and environment, and how consumers authenticate that state. |
| [#208, “Choose release-signer custody, recovery, and factor rotation”](https://github.com/nisavid/dotfiles/issues/208#issuecomment-5472198422) | Uphold. No assessed service should receive signer, recovery, or factor authority. Evidence-service and orchestration credentials remain separate and short lived. |
| [#209, “Define the signed release manifest and independent-admission protocol”](https://github.com/nisavid/dotfiles/issues/209#issuecomment-5474608513) | Keep JCS, SHA-512, RFC 9980, historical attribution, and the four-result algebra. Reopen only enough role/object/state layout to decide TUF-conformant POUF plus extensions versus explicit non-TUF delta. That choice blocks #213 and public contract freeze, not #212's planning disposition. Also reconsider the generic permanence of “one global state head,” “only one logical promotion may be in flight,” and human-signed <code>reaffirm</code> after #216 measures workload. Finally, decide whether manifest withdrawal intentionally permits the same artifact bytes to be rewrapped, or whether a subtractive per-scope digest quarantine is needed. |
| [#210, “Choose client trust bootstrap, refresh, and verification state”](https://github.com/nisavid/dotfiles/issues/210#issuecomment-5474715429) | Preserve refresh/pure-verification separation and retained anti-rollback/fork state. Add TUF-derived differential fixtures. Before client qualification, define what makes two bootstrap channels independently controlled and how the first trusted-time floor is established; otherwise the first-use mismatch and backward-clock claims are not portable tests. |
| [#214, “Research Cloudflare, Vercel, and GitHub publication capabilities”](https://github.com/nisavid/dotfiles/issues/214#issuecomment-5463592296) | No authority change. A GitHub reusable workflow, artifact attestation, or OIDC identity is orchestration/evidence and remains subordinate to exact signed objects and provider-neutral publication. |
| [#215, “Define the system threat and authority model”](https://github.com/nisavid/dotfiles/issues/215#issuecomment-5464747293) | Uphold the accepted first-use split-view residual risk. SCITT or a log receipt alone does not remove it. Revisit the named risk only when an independently witnessed service, monitor policy, retained checkpoint strategy, and PQ migration are concrete. |
| [#219, “Qualify age-plugin-fido2prf and choose its integration lanes”](https://github.com/nisavid/dotfiles/issues/219#issuecomment-5473754412) | No precedent-driven change. RFC 9980 support at the format level does not replace exact Sequoia, OpenSSL/backend, age, authenticator, and platform qualification. |

### Open decisions

| Decision | Recommended scope |
| --- | --- |
| [#212, “Specify the Agent Equipment release-authority consumer profile”](https://github.com/nisavid/dotfiles/issues/212) | State an Uptane/SUIT-like two-gate boundary: generic authenticity first, then a closed digest-bound Agent Equipment tuple and apply-authority decision. Only <code>accepted-current</code> crosses the seam; it still grants no execution or receipt authority. A serialized result is never the handoff. Name the exact generic artifact roles, profile identity, trust-state ownership, installed implementation identity, and bootstrap/self-update dependency. #212 may close as planning if it records the upstream TUF, bootstrap, and protected-byte-handoff dependencies rather than redefining them locally. |
| [#216, “Prototype the minimal release operator surface”](https://github.com/nisavid/dotfiles/issues/216) | Exercise the accepted human-signing and compare-and-swap workflow with two independent product/channel streams, simultaneous prepared promotions, stale heads, crash/retry, emergency freeze, signer rotation, and freshness reaffirm. Measure operations and failure recovery before the single global serialization becomes a permanent generic interface. |
| [#213, “Prototype the conformance and executable-documentation system”](https://github.com/nisavid/dotfiles/issues/213) | Build the cross-standard hostile corpus after #216 fixes the operator-visible contract. Include TUF-class attacks, RFC 9980 packet failures, JCS differentials, DSSE-style cross-type substitution, optional-evidence laundering, SHA-256/SHA-512 cross-binding, SCITT/RFC 3161 non-authority, all four generic outcomes, and fake-actuator zero-effect checks. |

## Decision language to reconsider

The evidence does not justify reopening the accepted cryptographic profile. It does justify tightening several generic claims before they harden into public compatibility promises.

1. **“One default signer serves the adopter's generic release namespace.”** Keep it for the single-operator first profile, but stop short of presenting it as the durable generic default. A compromised signer spans every product and channel in that namespace. TUF delegated targets and Uptane's separate repository roles show a maintained alternative. A later profile may need scoped signers or thresholds; the first release should reserve that evolution without inventing it now.
2. **“One global state head” and “only one logical promotion may be in flight.”** This makes cross-stream coherence simple and auditable, but serializes unrelated releases and emergency operations. The cost is unknown until #216 runs multi-stream and failure scenarios. Preserve the accepted rule for the prototype; decide after measurements whether it is a v1 invariant, a single-operator profile rule, or an implementation choice.
3. **Human-authorized positive <code>reaffirm</code> for bounded freshness.** This avoids an online key with positive authority, unlike TUF's minimally trusted timestamp role. It also creates recurring human liveness work. The first release should either accept that workload explicitly or define a narrower, non-positive freshness mechanism in a new decision. It must not quietly introduce an online signer through implementation convenience.
4. **Single certifying primary versus threshold root.** The accepted threat model already admits that certifying-root compromise ends automatic continuity. TUF makes threshold roots a primary compromise-resilience mechanism. Keep the single-root first profile only with a plain statement that multiple encrypted copies or factors protect one authority but do not provide independent signing thresholds.
5. **“RFC 3161 adapter” without a closed validation profile.** The decision is directionally correct but leaves interoperability and archival behavior underspecified. Name the imprint algorithm, exact subject bytes, nonce and policy behavior, RFC 5816 certificate identifier, retained chain and revocation material, clock/accuracy treatment, and renewal stance before two implementations can claim the same adapter.
6. **“Two independently controlled public channels.”** Name allowed channel classes and the controlling principal for each; two URLs, accounts, packages, or pages under one compromise domain are not independent merely because they look different. The persisted bootstrap receipt should record the public provenance and conflict outcome without introducing private account data.
7. **“A backward clock cannot extend freshness.”** Narrow this to “after a trusted time floor has been established and protected,” or require a provisioned or authenticated initial time. At first use, <code>max(local wall clock, retained floor)</code> has no useful retained floor if the local clock is stale.
8. **Qualification lifecycle without qualification authority.** A record that names a reviewer is evidence, not authority. Define the authenticated qualification issuer or threshold, its scope, predecessor and supersession rules, and the installed consumer policy. in-toto, DSSE, Notary, or SCITT can encode evidence but cannot grant the role.
9. **Manifest-only withdrawal.** The accepted rule permits the same artifact bytes to appear under a genuinely new manifest. Decide whether that is intentional wrapper-level invalidation. If incident policy needs “these bytes must not run again,” add a separately authorized subtractive artifact- or tuple-digest quarantine rather than overloading manifest withdrawal or freezing an entire scope.

These are reconsideration points, not authorization to edit accepted comments. If the first release intentionally keeps them, the compatibility document should state the resulting TUF status, single-operator failure domains, bootstrap assumptions, incident semantics, and operational-liveness tradeoffs.

## Wayfinder rescope proposals

The open map [#202, “Reusable post-quantum release trust and cryptographic operations”](https://github.com/nisavid/dotfiles/issues/202) should preserve the accepted core and sharpen the remaining work into separately answerable questions.

### Research: specify the TUF compatibility delta

**Question.** For every TUF 1.0.36 role, trusted state transition, attack class, and client/repository responsibility, where is the accepted protocol equivalent, stronger, weaker, or intentionally different?

**Required output.** A normative comparison, result-mapping table, and test inventory. It must decide whether the public implementation document is merely POUF-shaped or whether a real TUF-conformant profile is worth prototyping. It must not relabel the existing protocol as TUF.

**Dependencies.** Reads accepted #206, #209, and #210. It should feed #213. It need not block #212 if #212 records the generic gate as opaque and exact.

### Grilling: choose the release-state scalability profile

**Questions.**

- Is the first public profile explicitly single-operator and low-frequency?
- What maximum number of independent products/channels and what promotion rate must one global head support?
- Must an emergency freeze wait behind an unrelated promotion?
- Is human-signed freshness reaffirm acceptable at the shortest configured freshness interval?
- At what adoption boundary do scoped signers, thresholds, or state sharding become required rather than advanced?

**Dependency recommendation.** Run after the first #216 operator simulation and before freezing the global-head and default-signer choices as general v1 compatibility promises. It should not block a named single-operator Agent Equipment profile.

### Grilling: make bootstrap and initial time testable

**Questions.**

- Which public channel classes are permitted to confirm the fingerprint and canonical hostname?
- What proves that their controlling principals and compromise domains are independent?
- What public, value-free facts does the protected bootstrap receipt retain?
- What happens when one channel disappears, changes control, or conflicts after initialization?
- Is initial trusted time provisioned, authenticated by an independent source, or explicitly assumed from the local clock?
- Which freshness guarantee begins only after the first protected high-water time exists?

**Dependency recommendation.** This is part of the generic client profile under #210, not Agent Equipment policy. It blocks first client qualification and protected-consumer implementation. #212 may close only by recording the generic input as a dependency.

### Research and grilling: define qualification authority

**Research question.** Can the accepted qualification record be represented as an in-toto Statement and authenticated DSSE/OpenPGP envelope without importing the evidence system's identity policy, and what does RFC 9124's split between author and qualification authority require at the consumer?

**Decision questions.**

- Which key, role, or threshold may qualify an exact implementation, adapter, profile, environment, and fixture corpus?
- Can the release signer also qualify, or must some profiles require an independent qualification role?
- How are qualification activation, suspension, supersession, retirement, compromise, and historical interpretation signed and ordered?
- Which trust policy is installed independently of the candidate, and which result is produced when qualification state is stale, unknown, or conflicting?

**Dependency recommendation.** Decide before #213 publishes a “qualified” conformance result or any real adapter is supported. It does not block #212's semantic consumer mapping.

### Prototype: prove the generic-to-consumer zero-effect boundary

**Question.** Can one candidate-independent consumer kernel carry the exact bytes behind <code>accepted-current</code> into Agent Equipment's complete tuple gate and protected actuation transaction while proving that every other generic result and every tuple failure performs zero installer, archive, receipt, or credential operation?

**Required fixtures.** All four generic outcomes; profile and selector mismatch; cross-product substitution; accepted bytes with an invalid Agent Equipment tuple; digest change between admission, preparation, actuation, readback, archive, and receipt; candidate-selected adapter or destination; partial actuation; crash/retry; health failure; rollback failure; and candidate self-update.

**Protected-handoff constraint.** The launcher obtains the anchor, retained state, immutable profile, and trusted time from its own protected store; runs or re-runs admission; and binds the request, state heads, and result to held exact bytes or another immutable captured byte mapping. Caller-supplied result JSON, paths, or digests are diagnostics and requests, never capabilities. Installed bytes are rehashed before health, archive, or receipt processing.

**Dependencies.** #212 must first define the closed handoff. A separate generic consumer-actuation decision under #202 should own the public interface question. #213 then turns the accepted semantics into executable documentation.

### Research: close the external-evidence profiles

**Questions.**

- What exact RFC 3161/RFC 5816 profile and retained validation bundle can two implementations verify identically?
- Does the first release promise RFC 4998-style renewal or explicitly stop at evidence valid under a caller-supplied historical trust context?
- Which in-toto Statement and SLSA predicate versions are qualified, and how are every external digest and builder identity bound to local policy?
- What concrete SCITT API/profile, witness quorum, monitor, retention, privacy, and PQ conditions would justify moving from reserved type to adapter prototype?

**Dependencies.** #203 and #209 are inputs. This work may proceed beside the core and must not become a release availability gate.

### Grilling: choose wrapper withdrawal or byte quarantine

**Questions.**

- Does “withdraw” mean only that one signed authorization object is terminally barred?
- Which incidents require terminal rejection of the same artifact or Agent Equipment tuple under every later manifest in a scope?
- Which subtractive authority may quarantine a digest, and can only the certifying identity clear it through a new positive transition?
- How do historical attribution and archive evidence describe a quarantined artifact without implying that it remains safe to execute?

**Dependency recommendation.** This need not block the first single-product protocol if the wrapper-only limit is explicit. It must be settled before the Agent Equipment profile claims byte-level terminal compromise handling or before production incident procedures depend on it.

### Prototype: measure the minimal operator surface in #216

**Questions.**

- Can prepare, review, authorize, sign, independently verify, archive, upload, compare-and-swap, and readback be made clear without combining authority steps?
- How many human ceremonies does one ordinary release, freshness reaffirm, signer rotation, failed promotion, emergency freeze, and recovery require?
- Which state is safely retryable, which state must be reconciled by readback, and which state requires new authorization?
- Does a two-stream simulation expose unacceptable global-head contention or ambiguity?

**Dependency recommendation.** Keep #216 unblocked and use its outputs to answer the scalability grilling. Keep #213 dependent on the stable operator-visible objects and error classes, not on any provider or production signer.

### Prototype: make #213 the cross-precedent conformance corpus

The corpus should identify each case by the standard or invariant it exercises, while the expected result remains the accepted four-result algebra. It should include:

- TUF root rotation, freeze, rollback, fast-forward, mix-and-match, wrong-target, endless-data, consistent-snapshot, and crash-safe retained-state cases;
- Uptane-like image-authentic/consumer-unauthorized separation;
- SUIT-like side-effect-free condition failures before any directive;
- RFC 9980 partial-composite, packet, binding, issuer, and algorithm-confusion failures;
- JCS number, string, duplicate-key, Unicode, ordering, and cross-family parsing differentials;
- DSSE-inspired payload-type substitution;
- RFC 3161, SCITT, Sigsum, Sigstore, and hosted-attestation evidence that is valid but non-authoritative;
- external SHA-256 and authoritative SHA-512 mismatch;
- every non-current generic result producing zero consumer and actuator effects; and
- fake-actuator partial failure, readback mismatch, health rejection, rollback failure, archive conflict, and receipt misbinding.

## Uncertainties

- The accepted object families have not been mapped field by field through the TUF 1.0.36 client algorithm. JCS, SHA-512, and RFC 9980 can be POUF choices, but current evidence cannot establish whether a conformant role mapping preserves the global-head and historical semantics without wire changes.
- No qualifying public service was identified that combines SCITT-compatible receipts, independent witnesses or equivalent split-view defense, durable retained checkpoints, an RFC 9980-safe subject binding, and a post-quantum receipt path.
- SCITT's reference API and implementation profiles remain drafts even though the architecture and receipt RFCs are Proposed Standards.
- The SUIT manifest and related operational documents remain Internet-Drafts. Their final wire details may change.
- TUF TAP 21 is a draft and specifies pure ML-DSA, not the accepted OpenPGP composite.
- The JOSE/COSE composite-signature document remains a draft with unstable identifiers.
- Sigsum's log and cosignature formats are stable v1, but its proof-bundle and trust-policy formats are works in progress, and no service commitment was qualified for this use.
- Common RFC 3161, Sigstore, SCITT, CT, and witness deployments remain classical even when their hash-tree structure is useful. A post-quantum release signature does not make external evidence post-quantum.
- Standards and maintained reference implementations do not prove interoperability of every RFC 9980 packet path or cryptographic backend. Cross-implementation vectors remain a qualification need.
- The expected adopter count, number of release streams, promotion frequency, maximum offline interval, and acceptable human freshness workload are not yet measured. Those facts control whether one signer and one global head remain proportionate.
- The accepted bootstrap decision does not yet define channel-control independence or a first trusted-time source tightly enough for portable qualification fixtures.
- The intended authority for qualification records may be implicit in a future signed inventory, but no accepted decision currently closes that loop.
- It is not yet explicit whether manifest withdrawal intentionally permits later reauthorization of identical artifact bytes or whether some incidents require digest-level quarantine.
- A common public actuator interface is still a hypothesis. RAUC, systemd-sysupdate, Sparkle, and pacman expose enough variation that fake and then two-platform evidence should precede publication.

## Explicit exclusions

- This audit does not accept, amend, close, label, assign, or otherwise mutate any issue or decision.
- It does not authorize implementation, publication, signing, deployment, key generation, key transition, trust bootstrap, provider setup, protected installation, package-manager action, or Agent Equipment operation.
- It does not select a transparency, timestamp, CI, registry, or publication provider.
- It does not define production commands, paths, account identities, credentials, secrets, trust roots, or host configuration.
- RATS, EAT, CoRIM, and remote-attestation systems are excluded from the first-release recommendation because they report measured platform state rather than release authority or consumer apply authority.
- Omaha is excluded as an implementation dependency because its official repository is archived. Its service separation is historical design input only. [Omaha repository](https://github.com/google/omaha)
- OpenTimestamps, Roughtime, blockchain anchoring, software archives, and other observational systems remain outside the required path. They may be researched later as evidence but do not close authority, publication, or non-equivocation claims.
- No numeric score is assigned. TUF, SUIT, SCITT, Sigsum, and the platform updaters make different security and operational tradeoffs; reducing them to one rank would hide the boundaries this audit is meant to preserve.
