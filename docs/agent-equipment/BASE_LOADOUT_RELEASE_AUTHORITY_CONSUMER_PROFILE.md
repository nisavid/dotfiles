# Base Loadout release-authority consumer profile

**Status:** Accepted planning contract for [issue #212](https://github.com/nisavid/dotfiles/issues/212).

**Authority:** This document specifies a consumer profile. It does not authorize implementation, installation, provisioning, signing, verification of production releases, credential or authenticator access, trust-store mutation, archive mutation, fitting, or host changes.

## Purpose

Base Loadout uses the generic release-trust system to authenticate the exact protected components that validate and archive a release tuple. Generic admission remains separate from Base Loadout's complete release-tuple validation, release archive, release receipt, protected fitting, and host-migration authority.

The consumer profile has the immutable identity:

```text
io.nisavid.base-loadout.release-authority/v1
```

Its release scope is exactly:

```text
product: base-loadout
channel: production
purpose: release-authority
```

The identifiers above select one consumer policy. They do not grant authority. The signer still needs an active generic grant for that exact product, channel, and purpose under the release-trust protocol.

## Settled generic inputs

This profile consumes the following accepted contracts without changing them:

- [Issue #207](https://github.com/nisavid/dotfiles/issues/207#issuecomment-5470521497) separates the normative core, adapter interfaces, reference implementations, immutable public policy profiles, private deployment bindings, and qualification records.
- [Issue #209](https://github.com/nisavid/dotfiles/issues/209#issuecomment-5474608513) defines exact signed release objects and the side-effect-free `independent-admission/v1` evaluator. Its only outcomes are `accepted-current`, `attributed-historical`, `rejected`, and `indeterminate`. An admission request or result is not authority.
- [Issue #210](https://github.com/nisavid/dotfiles/issues/210#issuecomment-5474715429) defines trust bootstrap, refresh, retained state, offline freshness, manual rebootstrap, and protected verifier replacement. Verification performs no network or persistent-state operation.

The generic protocol's JCS, SHA-512, RFC 9580/9980 OpenPGP, authority, lifecycle, result-precedence, and retained-state rules remain unchanged. This profile may narrow behavior but cannot upgrade or reinterpret a generic result.

## Source and distribution model

One public Crypto Ops project owns the reusable release-trust implementation, compact verifier and installer interfaces, profile meta-model, adapters, reference implementations, fixtures, and conformance assets. Base Loadout does not require a bespoke release-authority repository.

Repository separation remains an optional defense-in-depth measure when a demonstrated ownership, privilege, dependency, or release-cadence seam justifies it. Repository location, review, CI, branch protections, build provenance, and hosted attestations can provide evidence. They do not become the cryptographic trust root.

The deployed design uses two independently versioned and admitted release streams:

1. The generic release-trust verifier and installer distribution.
2. The Base Loadout release-authority distribution, assembled from reusable consumer logic and the narrow Base Loadout hook that cannot be expressed in the public profile.

The currently trusted verifier and installer authenticate the exact bytes and compatibility of a candidate verifier before replacement. The candidate verifier does not verify, install, or declare itself compatible. A Base Loadout release-authority candidate cannot select or replace its verifier.

Shared source does not collapse the streams. Each stream has its own signed identity, immutable artifact digest, version, qualification evidence, acceptance pin, installed identity, protected state, and rollback evidence.

## Public profile and private binding

The immutable public profile fixes:

- its identity, version, digest, and exact release scope;
- required artifact roles and selector dimensions;
- compatible generic protocol, verifier, consumer, and adapter-interface versions;
- result handling and the ongoing-currentness rule;
- the generic-to-Base-Loadout handoff;
- required qualification and local-acceptance evidence classes;
- ownership separation and candidate-control prohibitions; and
- fail-closed behavior.

The private protected deployment binding supplies:

- the exact #210 trust-anchor pair and retained-state namespace;
- exact source and repository coordinates selected for the deployment;
- pinned verifier, installer, profile, and Base Loadout authority identities;
- protected verifier, launcher, schema, state, staging, and rollback locations;
- installed owners, groups, modes, service identities, and privileges;
- archive and trusted-digest destinations;
- qualified platform and dependency versions; and
- opaque references to any separately authorized private resources.

Dotfiles owns this deployment binding, protected installation, host-specific acceptance evidence, and later provisioning. Candidate-controlled source, configuration, paths, environment variables, arguments, or artifacts cannot select or override either the public profile or private binding.

## Required release artifacts

Each Base Loadout release-authority release has exactly two semantic artifact roles:

1. `installed-closure-manifest`: a closed manifest of the launcher, Base Loadout hook, schemas, entry point, supported interface and profile versions, and every installed byte the protected launcher must measure.
2. `platform-payload`: the immutable package or bundle from which that exact closure is staged.

Both roles use exact `os` and `arch` selectors. There is no implicit universal fallback. Adding a selector dimension or changing a role's meaning requires a new profile version.

The public consumer profile remains a separately digest-pinned profile reference. It is not a payload role and a candidate cannot replace it as part of the release it asks to admit. Source archives, SBOMs, build provenance, hosted attestations, SCITT evidence, and provider receipts remain typed evidence rather than required authority artifacts unless installed policy explicitly narrows this profile in a later compatible version.

The two artifact roles do not absorb Base Loadout's complete release tuple, release archive manifest, or release receipt. Those remain Base Loadout contracts.

## Ongoing currentness gate

Generic release admission governs both installation and each future operation that could issue a Base Loadout release receipt.

Before the protected release authority evaluates a release tuple, a candidate-independent installed component:

1. selects the protected profile, deployment binding, trust anchor, retained state, verifier, and installed authority closure;
2. refreshes generic trust state separately or uses complete, previously accepted, still-unexpired retained state;
3. measures the exact installed closure and evaluates it with `independent-admission/v1` under the fixed scope; and
4. continues only when the result is `accepted-current` for exactly the required manifest and payload.

`attributed-historical` supports audit only. `rejected` stops conclusively. `indeterminate` also stops, while retaining its distinct meaning as missing, stale, conflicting, unsupported, or unknowable required information. All three non-current outcomes cause zero Base Loadout tuple-validation, archive, release-receipt, fitting, credential, installation, or execution effects.

The pure verification operation performs no network access. Bounded offline operation is permitted only while the complete retained state remains within its signed freshness limit. An installed authority that is withdrawn, frozen, revoked, stale, or otherwise not currently admissible cannot issue a new release receipt merely because it passed admission when it was installed.

## Exact-byte handoff

A serialized generic result, caller path, caller digest, version string, URL, package-manager result, or SCITT receipt is diagnostic or request material. None is a bearer capability.

The protected component holds or independently resolves the exact admitted bytes, re-runs generic admission against its own protected inputs, and binds the request, selected state heads, manifest, envelope, profile, and both required artifacts to that byte mapping. The same generic SHA-512 artifact identities remain bound through staging, Base Loadout validation, installed-byte readback, archive, and receipt.

An acquisition, package-manager, or platform adapter may transport or stage only the already selected exact artifacts. It cannot choose a version, change the selector, follow an implicit latest channel, substitute a native trust result, or reselect the candidate after generic admission. Native platform checks may add defense in depth but cannot replace either gate.

The Base Loadout hook parses the authenticated `installed-closure-manifest`, recomputes the existing launcher identity and SHA-256 installed-manifest digest, and supplies those independently derived values to [issue #121](https://github.com/nisavid/dotfiles/issues/121). Installed-byte readback must match both the authoritative generic SHA-512 identities and the Base Loadout closure identity. Neither digest is silently converted into or substituted for the other.

Only then does #121 validate the complete release tuple defined by Base Loadout's current contracts. The generic verifier, this profile, and a platform adapter do not recreate, weaken, or partially satisfy that validation. A successful generic result does not become an additional release-tuple stream and does not make a tuple valid.

## Release archive and receipts

[Issue #122](https://github.com/nisavid/dotfiles/issues/122) retains ownership of create-only archival of one exact validated release tuple and its independently trusted release receipt. A receipt is emitted only after the durable archive commit. An identical-generation retry returns the same receipt; different bytes at that generation are a conflict.

Generic withdrawal, freeze, revocation, expiry, or later compromise evidence does not delete or rewrite existing immutable archives and receipts. They remain historical evidence and do not create new current authority.

Three similarly named records remain distinct:

- A **SCITT receipt** proves that a SCITT statement was included in one transparency-service view.
- A Base Loadout **release receipt** proves that the protected release authority durably archived one exact validated release tuple.
- A **Fitting Receipt** belongs to protected fitting and records its own completed fitting contract.

None can substitute for another. No SCITT or release receipt grants a Fitting Grant, Fitting Lease, fitting execution, or host-migration authority.

## External evidence

SCITT enters only through #209's typed external-evidence boundary. The reserved profile uses RFC 9943 terms and media types, RFC 9942 receipts, and an RFC 9995 SHA-512 bridge over the exact `signature-envelope/v1` bytes. The verifier independently rechecks the underlying OpenPGP release graph.

A valid SCITT statement or receipt cannot select current state, repair invalid authority, clear withdrawal or quarantine, authorize Base Loadout validation, mutate an archive, or issue any Base Loadout release receipt. Missing required SCITT evidence can make a later profile `indeterminate`; invalid optional evidence is only a diagnostic note. Production service selection, trust, monitoring, witnessing, and qualification remain later generic work.

Source review, reproducible-build evidence, in-toto or SLSA provenance, Sigstore, Notary, GitHub attestations, SBOMs, and provider readback can likewise be typed evidence. None upgrades a generic outcome or crosses directly into Base Loadout authority.

## Rollback, compromise, and recovery

- Rollback is a new, higher generic state generation that explicitly reselects an eligible historical manifest. Pointer rewind, version-only selection, and `attributed-historical` never authorize rollback.
- Generic freeze, withdrawal, signer revocation, expired freshness, rollback detection, or unresolved conflict stops new release operations according to #209 and #210.
- A compromised Base Loadout release-authority distribution is replaced only through the still-trusted generic verifier and installer path. If that path or anchor continuity is also untrusted, automatic recovery stops and #210's explicit manual-rebootstrap boundary applies. Candidate code does not perform recovery.
- Compromise of the protected installed owner, verifier host, or retained-state store is outside automatic continuity. Recovery requires separately authorized inspection and re-establishment of the protected boundary; deleting state or reinstalling candidate bytes is not rebootstrap.
- Existing archives and receipts remain immutable historical evidence during recovery.
- #209 withdrawal remains terminal for one manifest identity. This profile does not invent byte-level or tuple-level quarantine. A separate generic decision must define any per-scope artifact or tuple quarantine and the higher positive authority needed to clear it before Base Loadout can claim terminal rejection of the same bytes under every future manifest.

## Relationship to Base Loadout fitting

Base Loadout is a portable Loadout that becomes an exact Resolved Loadout and is combined with a Host Binding Profile to produce a Rig Manifest. Protected fitting separately reasons about Rig State, a Fitting Plan, preparation, authorization, execution, recovery, and evidence.

This release-authority profile authenticates the protected release components used at one release boundary. It does not validate a Resolved Loadout, Host Binding Profile, Rig Manifest, Rig State, or Fitting Plan. It grants no preparation authority, apply authority, Fitting Grant, Fitting Lease, Fitting Receipt, or migration authority. The candidate-independent preparation and protected-executor contracts keep their existing owners.

## Downstream disposition

[Issue #120](https://github.com/nisavid/dotfiles/issues/120), **Provision the protected release-authority boundary**, is the only existing issue that receives this profile directly. It owns the Base Loadout deployment binding, selected source coordinate, protected installation identities and destinations, archive and trusted-digest surfaces, local acceptance evidence, and the later provisioning record.

#120 must not implement its source, updater, installer, or protected-launcher surface until [#244, “Define the generic consumer updater and protected-launcher boundary”](https://github.com/nisavid/dotfiles/issues/244) closes. #120 must not presume a bespoke Base Loadout repository or fork the generic release-trust contract.

[Issue #121](https://github.com/nisavid/dotfiles/issues/121) remains downstream of #120 and remains the sole complete release-tuple validator. #122 remains downstream of #121 and owns archive and release-receipt semantics. The broader Step 8a and fitting graphs retain their current owners and ordering.

The #202 coordinator owns the exact map tickets and dependency edges for:

- TUF conformance or an explicit security delta before public wire and conformance freeze;
- independently controlled bootstrap channels and the initial trusted-time floor;
- authenticated qualification authority and lifecycle;
- the generic consumer updater and protected-launcher boundary;
- #213's public SCITT bridge and hostile fixtures;
- the generic SCITT evidence profile and later service qualification; and
- post-operator-prototype scalability choices.

These generic decisions do not reopen #212 or authorize #120 implementation. This profile records their dependency without creating a competing local contract.

## Required conformance evidence

Later implementation and qualification must use public disposable fixtures to demonstrate at least:

- all four generic outcomes, with only `accepted-current` reaching Base Loadout validation;
- zero privileged, archive, receipt, fitting, or credential effects for every non-current outcome and every tuple-validation failure;
- profile, selector, product, channel, purpose, role, and cross-product substitution failures;
- digest changes between admission, held bytes, staging, installation, readback, tuple validation, archive, and receipt;
- candidate attempts to select the anchor, profile, verifier, adapter, destination, entry point, health rule, or receipt meaning;
- stale, rolled-back, forked, frozen, withdrawn, revoked, and expired trust state;
- candidate verifier self-approval and incompatible verifier replacement;
- partial staging or installation, crash and retry, installed readback mismatch, health rejection, and rollback failure without authority or receipt escalation;
- archive retry, conflict, interruption, and false-receipt attempts;
- valid SCITT or other external evidence over a rejected, historical, or withdrawn release without an authority upgrade; and
- explicit separation of release receipts from Fitting Receipts and fitting authority.

Real platform adapters, privileges, production services, protected paths, keys, credentials, releases, and hosts remain outside this planning contract.
