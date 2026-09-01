# Generic release-trust consumer components

**Research date:** 2026-08-31

**Status:** Planning research only. This note is not an accepted decision, implementation contract, or authorization to build or deploy a verifier, installer, updater, launcher, signer, or release workflow.

## Verdict

Crypto Ops should own one public source project for the generic release-trust protocol, its pure verifier and retained-state client, compact CLI/library distributions, strict policy-profile meta-model, adapter contracts, reference adapters, fixtures, and conformance tests. Applications should normally contribute an immutable policy profile and a private deployment binding. They should contribute code only when their admission or actuation semantics cannot be expressed declaratively.

That project can also own the shared implementation used to assemble product-specific release-authority distributions. Base Loadout needs an independently versioned release-authority stream, but it does not need a bespoke implementation repository. Shared source, cryptographic authority, release stream, privileged installation instance, and application policy are different boundaries and must remain independently scoped.

A fully generic verifier is justified now. The generic verifier/installer distribution can own #210's bootstrap, refresh, and protected self-update coordination, while actual platform installation, ownership, and health mechanics remain adapters. A generic consumer updater or protected launcher for arbitrary applications is not yet justified: only its invariants are known. The transition from the pure four-result admission result to application admission and privileged actuation needs a separate Crypto Ops decision before it becomes a public interface. Base Loadout should be the first real consumer while that interface is developed, not the source of an application-specific implementation that is generalized later.

Existing infrastructure can reduce implementation work around the accepted protocol, but none of the systems assessed implements its combination of strict JCS objects, SHA-512 identity, OpenPGP v6 detached composite signatures, retained trust-state rules, four-result independent admission, and Base Loadout's tuple/archive/receipt rules. TUF supplies the closest updater-state architecture; in-toto, SLSA, Sigstore, Notary, and GitHub attestations can supply evidence; GitHub Actions can supply release orchestration; and systemd-sysupdate or Sparkle may become platform installation adapters. None should replace or silently weaken the accepted protocol.

## Settled constraints

### Accepted facts

- The reusable boundary already separates a public generic core, explicit adapter interfaces and reference implementations, immutable public policy profiles, private deployment bindings, and independent qualification. A seam becomes public only after real variation and conformance evidence justify it; adapter selection is explicit and fail-closed, with no ambient plugin discovery or fallback. The initial distribution remains together unless a real dependency, privilege, platform, ownership, or release-cadence seam requires a split. [Issue #207 resolution](https://github.com/nisavid/dotfiles/issues/207#issuecomment-5470521497)
- Independent admission is a pure operation over exact caller-supplied bytes. It performs no network or storage access and returns exactly one of `accepted-current`, `attributed-historical`, `rejected`, or `indeterminate`. Precedence is `rejected` over `indeterminate` over a positive result. The result is not a generic `allowed`, `safe`, or `may_execute` decision and is not itself authority to mutate or run anything. [Issue #209 resolution](https://github.com/nisavid/dotfiles/issues/209#issuecomment-5474608513)
- The accepted wire profile uses strict UTF-8 JCS objects, SHA-512 artifact identity, OpenPGP v6 detached type-`0x00` signatures, and the RFC 9980 algorithm-30 ML-DSA-65+Ed25519 composite with both components required. Authority is scoped by a stable authority domain and exact product, channel, and purpose. The generic protocol does not replace Base Loadout's complete release tuple, approval and attestation rules, candidate-independent launcher, create-only archive, durable receipt, or ownership and updater boundaries. [Issue #209 resolution](https://github.com/nisavid/dotfiles/issues/209#issuecomment-5474608513)
- Bootstrap and refresh have distinct operations. Retained protected state enforces anti-rollback, anti-fork, and time-floor rules and is replaced atomically only after the complete refresh transaction succeeds. The installed current verifier/installer authenticates a verifier update's exact bytes and compatibility before replacement; the candidate does not validate or install itself. Platform and package-manager mechanics are separately qualified adapters. [Issue #210 resolution](https://github.com/nisavid/dotfiles/issues/210#issuecomment-5474715429)
- Publication is provider-neutral at the protocol boundary. A provider adapter may publish immutable objects and compare-and-swap pointers, but provider evidence is not release authority and a mirror is not the canonical trust origin. [Issue #204 resolution](https://github.com/nisavid/dotfiles/issues/204#issuecomment-5469266482)
- Base Loadout requires a candidate-independent release launcher, exact validation of its complete release tuple and every required byte stream, a create-only content-addressed archive, and a receipt only after the archive is durable. The candidate cannot mint that receipt. [Current source context](../CONTEXT.md), [architecture](../ARCHITECTURE.md), and [implementation handoff](../IMPLEMENTATION_HANDOFF.md)
- The accepted [Base Loadout consumer-profile disposition](https://github.com/nisavid/dotfiles/issues/212#issuecomment-5494463333) fixes the mapping from generic trust into Base Loadout. Issue [#120](https://github.com/nisavid/dotfiles/issues/120) owns protected installation, binding, archive, and receipt surfaces; its discussion identifies repository separation as defense in depth rather than the source of trust. Issue [#121](https://github.com/nisavid/dotfiles/issues/121) retains independent validation of the complete authorization, action, capture, authority, checkpoint, terminal-state, evidence, and attestation tuple.

### Inference

The accepted protocol already fixes the verifier's semantic boundary, but it deliberately stops before consumer actuation. Therefore a generic verifier can be specified now, while a generic updater/launcher interface would be premature. Conflating the two would turn `accepted-current` into the generic authorization boolean that #209 explicitly rejects.

The repository boundary is also not a cryptographic boundary. A single source compromise may increase common-mode development risk, so source review and release automation still need compartmentalization, but separate authority domains, grants, signing keys, release streams, pins, installed identities, and protected state do the actual runtime isolation. This supports one shared implementation repository with independently released and installed assemblies; it does not support one shared key or one shared installed superuser service.

## Recommended architecture

### Source and distribution shape

Use one public Crypto Ops project with explicit internal packages and independently releasable assemblies:

| Layer | Generic ownership | Public boundary now? | What remains outside it |
| --- | --- | --- | --- |
| Protocol model and pure admission kernel | Strict parsing and canonicalization, digest and signature verification, authority graph evaluation, four-result aggregation, typed reasons, fixtures, and conformance vectors | Yes: the `independent-admission/v1` request/result contract accepted in #209 | Artifact discovery, network, storage, privilege, installation, execution, and application authorization |
| Verifier/installer client | Bootstrap ceremony inputs, root/state/archive refresh evaluation, anti-rollback/fork/time rules, protected self-update coordination, transaction construction, and the `initialize-anchor`, `refresh-trust`, `verify-current`, and `verify-historical` CLI/library operations accepted in #210 | Yes at the semantic operation boundary | Durable storage, locking, ownership, local clock policy, crash recovery, and platform packaging are adapter responsibilities |
| Policy profile meta-model | Closed schema for immutable, flattened, digest-pinned profile values; supported protocol capability declarations; profile fixtures and qualification records | Yes, once the profile is publisher-qualified under #207 | Host paths, accounts, secret locations, provider identifiers, and mutable deployment choices remain private bindings |
| Evidence adapters | Explicit adapters that retrieve or validate optional provenance and transparency material, producing evidence for the accepted request without changing authority precedence | Only adapters backed by real evidence sources and conformance fixtures | An evidence system never repairs invalid authority or turns a non-current result into permission |
| Authority-side engine | Shared construction and validation of signed release/state/archive objects, scoped grants, and publication requests | Shared source is recommended; each externally supported interface still needs #207 variation evidence | Signing custody, key selection, approval, product grants, and publication provider bindings stay separately scoped |
| Consumer launcher/updater kernel | Candidate-independent sequencing from generic admission to application admission and then actuation; exact artifact-digest continuity; fail-closed result handling | No. This is the missing Crypto Ops decision | Platform installation, privilege, application health, rollback, restart, and receipt semantics |
| Platform adapters | Linux/macOS acquisition, staging, ownership and mode changes, atomic replacement where available, service or application lifecycle, readback, and rollback | No common public shape until at least two qualified implementations demonstrate it | The generic core must not infer platform success from a transport or installer exit status alone |
| Application adapter | A narrow, pure application gate invoked only after `accepted-current`; for Base Loadout, the complete #121 tuple validation followed by its archive/receipt transaction | Application-specific by definition; common pieces can be promoted only after conformance evidence | Application policy, health, and receipt meaning must not leak into independent admission |

This is one source project, not one undifferentiated binary. At minimum it should be able to produce:

1. A compact generic verifier/installer CLI and library stream, with the retained-state and self-update coordination fixed by #210 and separately qualified platform installation adapters.
2. An independently versioned Base Loadout release-authority assembly composed from the generic consumer kernel, the Base Loadout profile, and only the narrow Base Loadout hook that cannot be expressed declaratively.

The second assembly may share most of its source with the first while retaining its own version, immutable artifact digest, review evidence, installation identity, protected state namespace, rollback history, and acceptance pin. Future applications should add profiles first and hooks only for genuinely different semantics.

### Generic interfaces

The following interfaces have stable generic meaning:

- **Pure admission:** exact request bytes and immutable profile identity in; one of the four #209 results plus typed diagnostics out. It must never expose a convenience authorization boolean.
- **Trust-state lifecycle:** explicit initialize, refresh, current verification, and historical verification operations. Refresh may fetch outside the pure evaluator, but validation and the proposed state transition remain pure; a protected storage adapter commits the whole accepted transaction.
- **Artifact identity:** the SHA-512 identity admitted by the core remains bound to the exact bytes handed to an application gate, installer, launcher, archive, and receipt. Version equality, URL equality, or a platform updater's candidate choice cannot substitute for this binding.
- **Profile identity:** callers select a closed, immutable profile by identifier, version, and digest. The candidate cannot supply or override its own profile, trust anchor, authority domain, product/channel/purpose tuple, adapter, destination, or entry point.
- **Capability declaration:** the installed trusted client declares the exact protocol/profile combinations it understands. Compatibility is checked by the current trusted client before a candidate update is installed, following #210.
- **Typed adapter outcomes:** storage, acquisition, installation, health, and rollback failures must remain distinguishable from `rejected` and `indeterminate`; they are not new independent-admission outcomes.

The following operations remain platform or application adapters:

- Artifact acquisition and transport, including registry, HTTPS, mirror, or local package behavior.
- Protected anchor/state locking, durable writes, ownership, ACLs, rollback storage, and crash recovery.
- Privilege acquisition and separation, staging layout, destination ownership and modes, symlink or service-unit changes, replacement, readback, and rollback.
- Process shutdown, launch, readiness, application-specific health checks, data migration, and recovery.
- Base Loadout tuple validation, binding of every required byte stream, create-only archive, durable receipt, and any meaning assigned to that receipt.

A generic orchestration kernel may call these adapters. It cannot truthfully implement them once for every platform and application.

### Protected launcher and self-update

The optional protected consumer should be an independently installed CLI/executable. Its reusable logic may be a library, but candidate code must not link, configure, or host the trusted decision path. Language-specific packages may prepare exact requests and decode typed results for a protected executable; they must not own anchors, select policy, perform privileged replacement, declare installation health, or convert a four-result result to permission.

The required sequence is:

1. The already installed launcher selects an immutable local profile and private deployment binding.
2. It obtains the candidate bytes and all signed inputs without executing the candidate.
3. The pure generic core evaluates those exact bytes.
4. Only `accepted-current` reaches the application gate. `attributed-historical`, `rejected`, and `indeterminate` cause zero installation, execution, archive, or receipt operations.
5. The application gate validates its complete contract. For Base Loadout, that is #121's complete release-tuple validation, including every required byte-stream check.
6. A protected platform adapter acts on the same admitted artifact identity, reads back the installed result, and performs application-specific health checks.
7. #122 archives the exact validated Base Loadout tuple and issues its release receipt only after its own durable-success rules are satisfied.

Self-update is a special instance of this flow. The current trusted verifier/installer uses a fixed verifier-update profile and protected binding to authenticate the candidate's exact bytes and compatibility, stages replacement, reads back the installed artifact, and retains a prior trusted copy or another qualified recovery path. The candidate is data throughout validation and installation. It never chooses the trusted profile, validates itself, runs a migration to establish its own trust, or replaces the process currently making the decision. These constraints follow the protected verifier-update boundary accepted in [#210](https://github.com/nisavid/dotfiles/issues/210#issuecomment-5474715429).

### Boundaries that must not collapse

| Boundary | Recommended scope | Why it remains separate |
| --- | --- | --- |
| Shared source code | One Crypto Ops project unless a demonstrated seam justifies a split | Reuse and one conformance corpus reduce divergent implementations; source location does not confer runtime authority |
| Cryptographic authority and keys | Stable authority domains and exact product/channel/purpose grants; custody and signer authorization scoped independently | Sharing an implementation must not broaden a key's grant or allow one product to authorize another; #209 makes the signed scope exact |
| Release streams | Independently versioned verifier/installer and Base Loadout release-authority artifacts, each accepted by immutable digest | A compatible source revision does not imply coordinated deployment or acceptance |
| Privileged installation instances | Per-product/profile service identity, binding, protected state, destinations, and rollback/archive namespace | A single privileged daemon serving unrelated products would enlarge the confused-deputy and common-failure surface |
| Application policy | Immutable public profile plus private deployment binding, with a narrow hook only for non-declarative semantics | Product policy must remain reviewable without forking the cryptographic engine |
| Publication | Provider-neutral signed objects plus explicit provider adapter and canonical origin | Provider success and hosted attestations are evidence, not authority, as #204 establishes |

The principal challenge to a shared repository is common-mode development and release-pipeline compromise. Address it with package boundaries, scoped ownership and review, independent build/release workflows, exact workflow and dependency pins, separate signing grants, separate artifacts, and independent consumer acceptance. Split the repository only if experience demonstrates that those controls do not isolate a real ownership, privilege, dependency, or release-cadence seam. That is the #207 rule applied to repository topology.

## Primary-source infrastructure assessment

### TUF and python-tuf

**Facts.** TUF bootstraps from trusted root metadata distributed out of band; updates roots sequentially with old-and-new root authorization; and uses timestamp, snapshot, and targets metadata with version, expiration, length, and digest checks to resist rollback, freeze, and mix-and-match attacks. Its consistent-snapshot scheme binds downloaded names to hashes or versions. [TUF specification](https://github.com/theupdateframework/specification/blob/master/tuf-spec.md) `python-tuf` exposes both a low-level metadata API and the higher-level `tuf.ngclient.Updater`, whose workflow refreshes metadata, selects targets, and downloads files through a fetcher abstraction. [python-tuf API](https://github.com/theupdateframework/python-tuf/blob/develop/docs/api/api-reference.rst) and [ngclient design](https://github.com/theupdateframework/python-tuf/blob/develop/tuf/ngclient/README.md)

**Compatibility limit.** TUF's specified metadata roles, signature and key formats, and documented Ed25519, RSA-PSS-SHA256, and ECDSA-P256 schemes are not the accepted strict JCS/OpenPGP-v6/RFC-9980 composite profile. Its high-level updater also combines refresh, target selection, and download, while #209 requires pure independent admission and denies generic actuation authority.

**Reuse.** Reuse its state-machine architecture, root-rotation and rollback/freeze test cases, consistent-download checks, fetcher separation, and crash-safe client-state lessons. A TUF client could be an additional transport or evidence adapter in an ecosystem that already requires it. It must not become the authoritative parser, release graph, trust result, or candidate selector for this protocol.

### in-toto and SLSA provenance

**Facts.** in-toto Attestation defines an envelope containing a statement whose subjects are identified by digests and whose predicate carries typed claims. The specification supports DSSE and defines validation as separate envelope, statement, and predicate checks. [in-toto Attestation v1](https://github.com/in-toto/attestation/blob/main/spec/v1/README.md) and [validation model](https://github.com/in-toto/attestation/blob/main/docs/validation.md) SLSA v1.2 build provenance is an in-toto predicate describing where, when, and how an artifact was produced. [SLSA provenance](https://slsa.dev/spec/v1.2/provenance)

**Compatibility limit.** An attestation subject digest can bind evidence to an artifact, but its envelope, signature policy, predicate vocabulary, and provenance claims do not establish the accepted release authority, current-state graph, or four-result precedence. Extensible predicates also conflict with treating the strict release/state/archive objects as open-ended bags of claims.

**Reuse.** Admit only explicitly named predicate types, attester identities, and subject digests through an evidence adapter. Keep their raw bytes and validation record in an `evidence-index` input. SLSA provenance can strengthen the evidence for a build; it cannot repair an invalid release signature or make an historical release current.

### Sigstore and Cosign

**Facts.** Sigstore's keyless model binds a short-lived Fulcio signing certificate to an OIDC identity and records signing events in Rekor. A Sigstore bundle can carry the verification material needed for later or offline verification, including a message signature or DSSE envelope, certificate chain, transparency-log entry, and timestamp material. [Sigstore bundle format](https://github.com/sigstore/docs/blob/main/content/en/about/bundle.md) and [Cosign signing overview](https://github.com/sigstore/docs/blob/main/content/en/cosign/signing/overview.md)

**Compatibility limit.** Fulcio/X.509 identity, Rekor inclusion, and Cosign/DSSE signatures form a different trust and wire profile from the required OpenPGP v6 algorithm-30 composite signature and retained authority state. A verified bundle proves only the policy expressed by its identity, issuer, signature, and transparency checks; it does not choose the current release or authorize installation.

**Reuse.** Use Cosign verification as optional source/build/OCI evidence, with exact issuer, identity, repository/workflow, and subject-digest constraints in a qualified evidence adapter. Keep the generic gate authoritative.

### Notary Project and Notation

**Facts.** Notary Project's signature specification binds signatures to OCI descriptors using JWS or COSE envelopes and an X.509 trust store/policy; OCI artifacts and referrers carry signatures and related artifacts. [Notary signature specification](https://github.com/notaryproject/specifications/blob/main/specs/signature-specification.md), [COSE envelope](https://github.com/notaryproject/specifications/blob/main/specs/signature-envelope-cose.md), and [trust-store/trust-policy specification](https://github.com/notaryproject/specifications/blob/main/specs/trust-store-trust-policy.md)

**Compatibility limit.** Its descriptor, envelope, certificate, revocation, and expiry policies are not the accepted release objects, OpenPGP signature profile, grant graph, or retained current-state rules.

**Reuse.** If an OCI registry is selected as a transport or mirror, a Notation result can be additional registry evidence and its descriptor digest can be checked against the admitted artifact. It cannot replace the canonical release origin or generic admission result.

### GitHub reusable workflows, OIDC, environments, and artifact attestations

**Facts.** A reusable workflow invoked by another workflow exposes the reusable workflow identity in the `job_workflow_ref` OIDC claim, allowing a cloud policy to bind short-lived credentials to the central workflow. GitHub recommends pinning an action to a full commit SHA as the only immutable release form. [OIDC with reusable workflows](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows), [OIDC claims](https://docs.github.com/en/actions/reference/security/oidc), and [immutable action pins](https://docs.github.com/en/actions/how-tos/create-and-publish-actions/manage-custom-actions) GitHub environments can restrict deployment branches or tags and apply protection rules such as required reviewers and wait timers; environment secrets are withheld until those rules pass, subject to repository and plan availability. [Deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments) GitHub artifact attestations generate signed provenance and can be verified against owner, repository, and workflow constraints. GitHub states that an attestation establishes where and how an artifact was built, not that the artifact is secure. [Artifact attestation concepts](https://docs.github.com/en/actions/concepts/security/artifact-attestations) and [verification](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)

**Compatibility limit.** A hosted workflow, environment approval, OIDC claim, or GitHub attestation is hosted orchestration/evidence. It is not the offline release authority, retained state, current-head decision, or consumer installation result. Repository or workflow identity alone also does not express the exact product/channel/purpose grant.

**Reuse.** Centralize repeatable build, test, provenance generation, and provider publication in full-SHA-pinned reusable workflows. Use OIDC instead of long-lived provider credentials where the provider supports it. Feed verified artifact attestations into an evidence adapter, and keep release signing approval, signed state transition, canonical publication, and consumer acceptance as distinct gates.

### systemd-sysupdate

**Facts.** `systemd-sysupdate` is an experimental Linux/systemd mechanism for updating files, directories, or partitions from declarative transfer definitions. It supports versioned resource instances, retention, and A/B-style schemes. Remote file/tar sources enumerate `SHA256SUMS` and `SHA256SUMS.gpg`; `Verify=` uses OpenPGP verification from system or local keyrings, while local source types do not perform equivalent source authentication. Multiple transfers are written and renamed in order, but the final activation of all resources is explicitly not atomic. [systemd-sysupdate manual](https://github.com/systemd/systemd/blob/main/man/systemd-sysupdate.xml) and [sysupdate.d transfer definitions](https://github.com/systemd/systemd/blob/main/man/sysupdate.d.xml) The D-Bus service exposes update operations to unprivileged clients through Polkit, with the shipped policy distinguishing update-to-latest from an administrator-authorized explicit older version. [service manual](https://github.com/systemd/systemd/blob/main/man/systemd-sysupdated.service.xml) and [Polkit policy](https://github.com/systemd/systemd/blob/main/src/sysupdate/org.freedesktop.sysupdate1.policy)

**Compatibility limit.** Its SHA-256 checksum-list/OpenPGP keyring policy, automatic version selection, Linux/systemd scope, local-source verification gap, default privilege policy, and non-atomic multi-resource activation do not satisfy the accepted release profile or prove application health and receipt durability.

**Reuse.** It is a candidate Linux installation adapter after the generic and application gates accept an explicitly selected artifact. Qualification would need to prove exact artifact handoff, disable native candidate ambiguity, constrain Polkit and destinations, order the entry point last where multiple resources are unavoidable, read back the installed digest, and define rollback and health behavior. It must not perform the authoritative candidate selection or replace the generic gate.

### Sparkle

**Facts.** Sparkle is a macOS application-update framework. Its documented security model verifies an appcast update with an EdDSA public key embedded in the installed application's `Info.plist`, may also validate Apple code signing, and uses isolated helper/XPC processes for downloading or privileged installation in supported configurations. The installed application can influence update selection through `SPUUpdaterDelegate`. [Sparkle security and reliability](https://sparkle-project.org/documentation/security-and-reliability/), [sandboxing and helper architecture](https://sparkle-project.org/documentation/sandboxing/), and [`SPUUpdaterDelegate`](https://sparkle-project.org/documentation/api-reference/Protocols/SPUUpdaterDelegate.html)

**Compatibility limit.** Sparkle's appcast, EdDSA key, Apple signing, delegate-driven selection, candidate packaging, and application-integrated framework are not the accepted generic release/state/profile contract. Embedding the only trusted gate in candidate-controlled application code would also violate Base Loadout's candidate-independent launcher boundary.

**Reuse.** Sparkle may provide macOS download, user experience, staging, and installation mechanics after an external protected launcher admits exact bytes and constrains the selected update. Its native checks can remain defense in depth. A qualified adapter must demonstrate that the installed trusted component, not the candidate or its appcast delegate, selects the fixed profile and exact admitted artifact and verifies the installed result.

### Overall infrastructure finding

TUF is the strongest architectural reference for protected refresh and rollback resistance. The provenance and signing ecosystems are strongest as evidence producers. GitHub Actions is strongest as orchestration. systemd-sysupdate and Sparkle are strongest as platform-specific actuators. Their differences support the proposed separation between pure generic admission, optional evidence adapters, a still-unsettled consumer actuation contract, and qualified platform/application adapters. They do not support substituting an existing updater's native trust decision for the accepted protocol.

## Development order and smallest useful prototype

### Recommendation: contract-first co-evolution

Do not design every generic interface in isolation, and do not build a bespoke Base Loadout release authority and extract it later. Co-evolve a thin generic kernel with one demanding real consumer:

1. **Freeze only accepted contracts.** Record #209's pure request/result and #210's retained-state operations as the first public surfaces. Keep storage, installer, launcher, health, and rollback interfaces internal and experimental.
2. **Resolve the generic consumer boundary.** [#244, “Define the generic consumer updater and protected-launcher boundary”](https://github.com/nisavid/dotfiles/issues/244) owns the pure-admission-to-application-admission-and-actuation decision. It should decide protected process ownership, exact-byte handoff, adapter authority, self-update, health/rollback results, language bridge limits, and qualification evidence. This work does not belong in the accepted #212 profile or the generic protocol/profile decision.
3. **Build a fixture-only vertical slice after that decision is authorized.** Use the generic four-result fixture output, a Base Loadout tuple fixture, a fake protected installer, and an in-memory create-only archive/receipt sink. No signing keys, network, package manager, privilege, or production path is needed.
4. **Exercise real variation before publication.** Implement or model two materially different adapter families—for example, a Linux/systemd-shaped staged replacement and a macOS/Sparkle-shaped application update—and use their conformance evidence to decide whether one public adapter contract exists. Keep platform extensions private until then.
5. **Implement and qualify independent distributions.** Release the generic verifier/installer and Base Loadout release-authority assemblies separately, with independent pins, protected bindings, state, rollback evidence, and acceptance.

The smallest useful prototype answers one question:

> Can one candidate-independent consumer boundary carry an `accepted-current` result and the exact admitted artifact into Base Loadout's full tuple gate and then into a protected actuation transaction, while guaranteeing that every other generic result and every tuple failure produces zero installer, archive, and receipt effects?

Its required negative fixtures are: `attributed-historical`, `rejected`, and `indeterminate`; accepted generic bytes with a failed Base Loadout tuple; a digest mismatch between generic admission and actuation; candidate attempts to choose a profile, adapter, destination, or entry point; installer readback mismatch; and a candidate verifier claiming compatibility for itself. This prototype tests the missing boundary rather than the already accepted cryptography. It belongs to [Define the generic consumer updater and protected-launcher boundary](https://github.com/nisavid/dotfiles/issues/244) and does not reopen the accepted Base Loadout profile.

### Why not extract later

Base Loadout alone cannot demonstrate which launcher or installer details are genuinely generic. Extracting from a finished Base Loadout implementation would risk publishing its root-owned paths, archive semantics, receipt meaning, and complete release tuple as accidental generic interfaces. Conversely, designing the updater without Base Loadout would not test the strongest known consumer constraints. Contract-first co-evolution applies #207's requirement directly: publish the pure surface already backed by accepted semantics, and promote an actuation seam only when a second implementation and conformance corpus show real variation.

## Issue consequences

### Accepted Base Loadout profile

The accepted #212 disposition concludes without selecting a platform updater or creating a bespoke repository. It records:

- A generic trust gate runs before every Base Loadout release-receipt operation.
- Only `accepted-current` crosses into Base Loadout admission; the other three outcomes have no release-authority effects.
- The exact admitted artifact identity remains bound through #121 validation and protected actuation, then through #122 archival and release-receipt issuance.
- The generic verifier/installer and Base Loadout release-authority are independently versioned and accepted streams, even when assembled from one Crypto Ops source project.
- Base Loadout supplies a declarative immutable profile and private deployment binding, plus only a narrow candidate-independent hook that supplies authenticated inputs to #121 and #122 without owning either semantic contract.
- [#244](https://github.com/nisavid/dotfiles/issues/244) owns the consumer updater/protected-launcher public boundary under the #202 map.

### Issues #120, #121, and #122

Issue #120 retains ownership of Base Loadout's protected binding, installed identities and destinations, protected archive and receipt surfaces, and deployment evidence. Its source/updater/launcher portion waits for #244 and subsequent implementation; it must not presume a bespoke Base Loadout implementation repository. Issue #121 remains the sole complete release-tuple validator and is invoked after generic `accepted-current`; neither the generic core nor a platform installer duplicates or weakens it. Issue #122 owns create-only archival and release-receipt semantics.

Implementation remains beyond this planning note. #120 stays blocked by [#244](https://github.com/nisavid/dotfiles/issues/244), which in turn stays blocked by [#243](https://github.com/nisavid/dotfiles/issues/243), until those decisions close in their owning lanes.

## Unresolved questions

One question genuinely needs prototype evidence: whether a single candidate-independent actuation boundary can cover both install-and-run consumers and execute-only consumers without giving an application hook ambient privilege or allowing the platform adapter to reselect the candidate. The fixture-only Base Loadout vertical slice should answer the semantic half; a later Linux/macOS pair should answer whether the adapter interface is portable enough to publish.

The implementation language, package layout, service manager integration, platform health criteria, rollback mechanism, and exact distribution naming remain decisions for #244 and later qualification. None changes the recommendation to share source while keeping authorities, streams, installed instances, and application policy separate.
