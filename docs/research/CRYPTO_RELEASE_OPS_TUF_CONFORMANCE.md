# TUF 1.0.36 conformance and security delta

## Decision

The accepted io.nisavid.release-trust/v1 protocol must remain explicitly non-TUF. It is TUF-informed, but it does not implement TUF 1.0.36's mandatory root, targets, snapshot, and timestamp metadata or its client update algorithm. A custom POUF cannot replace those requirements. Adding them now would change the accepted authority and client contracts or create the forbidden second authority plane.

No unresolved policy choice changes that result. A future TUF redesign is possible, but it is a new architecture decision, not an editorial completion of the accepted protocol.

## Evidence boundary

This comparison uses the accepted [release topology](https://github.com/nisavid/dotfiles/issues/206#issuecomment-5465835347), [manifest and admission protocol](https://github.com/nisavid/dotfiles/issues/209#issuecomment-5474608513), [client state](https://github.com/nisavid/dotfiles/issues/210#issuecomment-5474715429), [bootstrap clarification](https://github.com/nisavid/dotfiles/issues/243#issuecomment-5528378694), [threat and authority model](https://github.com/nisavid/dotfiles/issues/215#issuecomment-5464747293), and immutable [precedent audit](https://github.com/nisavid/dotfiles/blob/651607c1d67292afba437acd8e14c531cd990217/docs/research/CRYPTO_RELEASE_OPS_PRECEDENT_AUDIT.md).

The normative target is the tagged [TUF specification version 1.0.36](https://github.com/theupdateframework/specification/blob/v1.0.36/tuf-spec.md), dated 2026-08-05. [TAP 11](https://github.com/theupdateframework/taps/blob/master/tap11.md) defines POUFs.

This is a specification-level finding. No Release Trust client implementation, production setup, or passing conformance run was supplied or qualified.

## What a POUF can change

TUF's [document-format rules](https://theupdateframework.github.io/specification/v1.0.36/#document-formats) permit another deterministic encoding and additional signed fields only when every TUF field remains present and unambiguous. TUF also permits adopter-defined key types and signature schemes. RFC 8785 JCS, SHA-512 content digests, detached OpenPGP signatures, and RFC 9980 algorithm 30 are therefore possible POUF choices; they are not the blockers.

A POUF documents an implementation of TUF. It does not redefine TUF. TAP 11 requires protocol, operations, usage, and formats, including root, snapshot, targets, delegated-targets, and timestamp formats. It says a POUF should cover a working implementation and identify its versions. A named extension may add history, status, bootstrap, or application results only after the mandatory TUF roles and checks exist. It cannot replace a role, required field, threshold, expiry, or client step.

The accepted schemas are closed, and their own rule says core meaning requires a new family version rather than an extension. Hiding missing TUF fields inside an opaque extension would satisfy neither contract.

## Field-by-field mapping

The required role fields come from TUF's [root](https://theupdateframework.github.io/specification/v1.0.36/#file-formats-root), [targets](https://theupdateframework.github.io/specification/v1.0.36/#file-formats-targets), [snapshot](https://theupdateframework.github.io/specification/v1.0.36/#file-formats-snapshot), and [timestamp](https://theupdateframework.github.io/specification/v1.0.36/#file-formats-timestamp) sections.

| Area | TUF 1.0.36 requirement | Accepted protocol | Finding |
| --- | --- | --- | --- |
| Root | One signed root subject has the required role type, specification version, positive version, expiry, keys, and roles. Roles must name root, targets, snapshot, and timestamp key IDs and thresholds of at least one. The `consistent_snapshot` Boolean is optional for backward compatibility and SHOULD appear in new implementations; the repository and client must follow the selected mode. | The certifying OpenPGP identity, grants, authority state, root transition, and certificate projection jointly describe authority. No object carries the complete TUF root fields or role assignments. | Mandatory root metadata is absent. |
| Targets | Signed targets metadata has role type, specification version, version, expiry, and a targets map. Each target has a path, length, hashes, and optional custom data. | A release manifest binds exact artifact identities, roles, selectors, media types, lengths, and SHA-512 addresses. It deliberately has no acceptance expiry; its display version is not metadata precedence. | Useful target-like data, but no TUF targets subject, version, expiry, or role signature. |
| Snapshot | Signed snapshot metadata has role type, specification version, version, expiry, and entries for top-level and every delegated targets metadata version, with optional lengths and hashes. | Authority and release state alternate on one signed global chain and resolve a complete stream map. | Strong graph coherence, but no snapshot role, targets-metadata version list, or snapshot expiry. |
| Timestamp | Signed timestamp metadata has role type, specification version, version, expiry, and only a description of snapshot metadata. It is refreshed frequently. | The mutable pointer is unsigned and non-authoritative. Freshness comes from signed state, stream valid-until values, retained trusted time, and human reaffirmation. Status authority cannot renew positive freshness. | No timestamp metadata or timestamp role. |
| Signature envelope | TUF metadata signatures identify authorized key IDs. Each distinct key contributes at most once toward the role threshold defined by root or delegating targets metadata. | One unsigned content-addressed signature envelope carries one detached OpenPGP signature, full fingerprint, certificate projection, grant, and state references. Both RFC 9980 components must verify. | Authenticity machinery exists, but not TUF key-object, key-ID, role, or threshold semantics. |
| Thresholds | Every role has a positive threshold. TUF permits threshold one and even one key reused everywhere, while calling that insecure. | One active release signature is sufficient. Old and new roots both sign a transition. | Threshold one is not itself a blocker; missing role-declared thresholds are. The two RFC 9980 components are one composite signature, not two independent threshold keys. Transition signatures are not ongoing role quorums. |
| Delegation | Targets metadata may delegate ordered path scopes to named roles with keys, thresholds, terminating behavior, and paths or SHA-256 path-hash prefixes. Delegated targets roles may recurse. | The certifying identity directly grants a non-transitive leaf either the authority domain or finite exact product, channel, and purpose tuples. The leaf cannot delegate or widen scope. | Intentional authority-model difference. Recasting it as TUF delegation changes who creates positive authority. |
| Versions and rollback | Each metadata role has its own version. Root advances exactly N+1; timestamp, snapshot, and targets versions participate in retained rollback checks. | A global generation alternates authority and release changes; family, grant, and scope generations and exact predecessor hashes add other monotonic checks. | Comparable goal, different version model. A global generation cannot substitute for all TUF role versions. |
| Expiry and freshness | Root, targets, snapshot, and timestamp each expire. The client fixes update-start time and checks expiry at defined steps. | Grant intervals, signing time, bounded authority freshness, release-state valid-until, compromise cutoffs, and the maximum of wall time and retained trusted time govern results. | Coherent but different. Required TUF expires fields and role-specific checks are absent. |
| Consistent snapshots | The feature is optional. The root selects enabled or disabled behavior; new implementations SHOULD include the optional `consistent_snapshot` Boolean, while omission denotes disabled behavior for backward compatibility. When enabled, non-timestamp metadata uses version-prefixed names, targets use hash-prefixed names, and current timestamp is unversioned. The repository keeps every root version available in either mode. | All objects use SHA-512 addresses; publication uses immutable objects, exact graph links, compare-and-swap, and atomic retained transactions. | Similar race resistance, not TUF consistent snapshots. Choosing false would not excuse missing roles. |
| Extensions | Unknown TUF attributes remain signed, hashed, preserved, and unambiguous; mandatory meaning remains mandatory. | A signed namespaced map marks extensions critical or noncritical. Unknown critical semantics fail closed; permitted noncritical values are preserved and ignored. | Sound Release Trust discipline, but it cannot backfill TUF base fields. |
| Repository surface | A TUF repository exposes the four logical top-level metadata files plus any delegated-targets metadata. | Release Trust defines twelve different object families, a mutable state location, immutable objects, and unsigned indexes. | No complete TUF message set exists. |

### Sequential root updates

TUF's [root update](https://theupdateframework.github.io/specification/v1.0.36/#update-root) begins with trusted root N, downloads every N+1 root, verifies each against both the old and new root thresholds, persists each intermediate, and finally checks expiry. Rotation of timestamp or snapshot keys clears their cached metadata to recover from fast-forward attacks. The repository keeps every released root version available.

Release Trust requires old-root and new-root signatures over the same transition, the old root's OpenPGP direct-key certification of the new primary, proof of new-key possession, predecessor continuity, announcement lead time, archive closure, and atomic cutover. Those are meaningful protections. They still do not produce complete N+1 TUF root metadata, old and new TUF threshold evaluation, intermediate TUF root persistence, or TUF cache-key-rotation recovery. The mapping is therefore nonconformant, not merely extended.

### Client fetch and verification order

TUF's [detailed client workflow](https://theupdateframework.github.io/specification/v1.0.36/#detailed-client-workflow) is security-critical: fix time; load trusted root; update sequential roots; fetch and verify timestamp; fetch snapshot exactly as timestamp names it; fetch targets exactly as snapshot names it; traverse bounded ordered delegations; then fetch the target by declared length and verify its hash.

Release Trust instead establishes a fingerprint, canonical DNSSEC hostname, exact profiles, and qualified initial time through two independent channels; fetches the canonical HTTPS pointer and addressed graph; treats pointers, mirrors, and indexes only as retrieval hints; verifies complete root, grant, state, global-history, freshness, anti-rollback, and fork evidence; atomically commits the whole retained transaction; and later runs a side-effect-free evaluator over caller-supplied bytes.

The accepted order is deliberate, but it is not TUF's root-to-timestamp-to-snapshot-to-targets-to-target algorithm. Renaming graph objects or documenting them in a POUF cannot repair that difference.

## Admission, history, bootstrap, and retained state

TUF supplies verification and abort conditions but leaves application-specific error action to the updater. The accepted four results can be application semantics only; they cannot replace the missing TUF base checks.

| Result | Accepted meaning | TUF relationship |
| --- | --- | --- |
| accepted-current | Every current schema, signature, authority, scope, graph, freshness, lifecycle, rollback, selector, and artifact check passed. | Closest to successful current target verification, but not a TUF success because no TUF role chain ran. |
| attributed-historical | Complete archive closure supports attribution at an explicit past time. It never means current, safe to run, reinstallable, or promotable. | No TUF 1.0.36 positive result matches it. It is a separate application claim. |
| rejected | A conclusive protocol, cryptographic, authority, namespace, lifecycle, withdrawal, revocation, rollback, artifact, or policy violation exists. | Some TUF failures are likewise conclusive, but this enum is not a TUF result. |
| indeterminate | A required input is missing, stale, expired, conflicting, unsupported, or unknowable without conclusive invalidity. | Closest to an update that cannot safely complete. It never bypasses a required check. |

Precedence remains rejected, then indeterminate, then the mode-appropriate positive result. Invalid optional evidence adds only a note when required proof is otherwise complete. No result grants execution or installation authority.

TUF assumes a good root delivered out of band and explicitly does not solve arbitrary new-software bootstrap. Release Trust adds a two-independent-channel fingerprint and hostname ceremony, qualified initial-time evidence, DNSSEC and exact-origin refresh, profile locks, and explicit manual rebootstrap. DNSSEC authenticates bootstrap and retrieval; it does not issue positive release authority. These are additional security properties, not a TUF root file.

A TUF client persists current trusted role metadata; the repository keeps every released root version available for sequential updates. Release Trust retains the anchor, profile locks, highest accepted global and family generations and heads, highest trusted time, freshness observations, complete usable state, and observed forks. It atomically commits a complete graph. Valid competing successors remain evidence and yield indeterminate; they never overwrite the accepted chain.

Release Trust also retains signed transitions, grants, certificates, signatures, revocations, withdrawals, compromise cutoffs, and archives for historical attribution. TUF 1.0.36 has no equivalent positive historical-attribution mode. Unknown cutoff or incomplete closure remains indeterminate.

## Security delta

This compares intended mechanisms, not qualified implementations. TUF permits choices such as threshold one and key reuse, so compromise resistance depends on deployment.

| Concern | TUF | Release Trust and residual delta |
| --- | --- | --- |
| Arbitrary or wrong file | Verified targets metadata binds requested path, length, and hashes. | The signed manifest binds exact stream, artifact roles, selectors, length, and SHA-512 bytes. Comparable intent; implementation and consumer binding remain unqualified. |
| Endless data | Clients use declared lengths, download caps, root-update limits, and delegation-visit limits. | Artifact lengths and bounded fields exist, but every metadata byte cap, history count, graph depth, archive count, and fork capacity is not yet frozen. Those limits are downstream obligations. |
| Extraneous dependencies | Trusted targets plus application policy constrain files. | The atomic manifest requires exactly one artifact per required role and rejects missing, duplicate, ambiguous, overlapping, or foreign selections. Strong application control if the consumer profile is protected. |
| Fast-forward and rollback | Per-role versions and retained metadata detect rollback; rotating timestamp or snapshot keys clears caches for recovery. | Exact predecessor links, one-step generations, high-water marks, and fork retention detect simple skips and rewinds. There is no equivalent cache-clearing recovery rule; a compromised authorized signer can create a long valid branch. |
| Freeze | Frequently refreshed, expiring timestamp metadata exposes stale views. | Signed freshness, retained time, and human reaffirmation make stale state indeterminate; subtractive expiry never restores authority. Detection is comparable, but liveness depends on human release-signing rather than a minimally trusted online timestamp role. |
| Malicious mirror | Signatures and hashes prevent forgery; a client can try good mirrors. | A mirror returns only already authenticated addresses and cannot choose a head. Integrity is strong, but canonical DNSSEC and HTTPS outage can block discovery of new state. |
| Mix-and-match | Timestamp binds snapshot; snapshot binds all targets metadata. | The alternating global head, cross-family references, complete stream map, immutable envelope, and atomic commit bind one graph. Strong analogous property, not the TUF role chain. |
| Key compromise | Separate online and offline roles, delegation, and configurable thresholds can limit one key; insecure one-key layouts remain allowed. | A release signer can sign its manifests and positive lifecycle transitions only within its fixed, non-transitive grant; it cannot widen scope, add signers, change policy, or transition the root. Status authority is subtractive only. This resembles threshold-one TUF only for single-key current-content authorization within scope. A TUF key reused for root and every role can also replace role keys and thresholds and authorize targets, so its compromise has a broader blast radius. A Release Trust compromise remains authoritative within the grant until detected. |
| Hybrid signature | TUF permits adopter-defined schemes; thresholds count independent authorized keys. | RFC 9980 algorithm 30 provides algorithm diversity only. Both components share one signer and do not provide an operator quorum. |
| Delegation and incident state | TUF path delegation limits target authority; expiry and key rotation support recovery. | Exact non-transitive root grants are narrower; freeze, withdrawal, retirement, and positive-transition barriers are richer. They are application semantics, not TUF role replacements. |
| Equivocation | TUF binds one update's timestamp, snapshot, and targets metadata and checks specified version rollbacks. It has no predecessor-hash or witness rule for detecting a higher-version, fully authorized divergent view. The absence of protection against this monotonic equivocation is an inference from the workflow and its enough-keys-compromised threat boundary. | Returning clients retain observed forks and channel conflicts. Unwitnessed first-use split view remains an explicit residual risk; the client must not claim detection when it saw only one view. |
| Bootstrap and clock rollback | TUF assumes out-of-band root delivery and a suitable clock; an update uses fixed start time. | Two independent bootstrap channels, qualified initial time, and retained highest trusted time add defenses. A backward clock cannot extend freshness; a forward clock may deny service. |
| Key retention and history | The repository keeps every released root version available; the client persists current trusted metadata for rollback checks. | Broader archives allow bounded old-signer attribution. This increases archive and parser obligations. Old keys never regain current authority; unknown compromise timing is indeterminate. |
| Extension ambiguity | POUFs define wire meaning; unknown attributes stay signed and preserved. | Criticality is explicit and fail-closed. Downgrade, duplicate, conflict, and core-semantic smuggling still require hostile tests. |
| Availability and publication | Role separation permits different cadences; consistent snapshots avoid partial repository views. | One compare-and-swap global head and full atomic commit maximize coherence but serialize all changes. Availability failure never becomes positive authority. |

## Why a wrapper is not a solution

Aliasing current objects leaves mandatory fields and checks absent. Independently signed TUF metadata would add root, targets, snapshot, and timestamp authority with separate versions, expiries, and compromise behavior. If trusted, that is a second authority plane; if not trusted, it cannot establish TUF trust.

Publishing Release Trust objects as opaque TUF targets could be a future distribution layer. TUF would authenticate delivery while Release Trust separately decided admission. That would not make Release Trust a TUF POUF, and the authority precedence would require a new decision.

## Required hostile fixtures

Each semantic-negative fixture must remain cryptographically valid under a disposable fixture authority long enough to reach its intended policy check. Every case binds the exact request, operation-specific result or disposition, deterministic diagnostics, and retained-state delta.

Publication keeps its producer-side promotion outcome, initialization and refresh use their own typed dispositions and exit classes, and admission uses its four outcomes. Each fixture binds the closed diagnostic for its owning operation instead of translating it into another operation's result.

| Family | Minimum cases | Expected result and state |
| --- | --- | --- |
| Rollback | Lower any retained generation; replay an old head; omit retained history; rewind a pointer; present an old release without a higher reselect. | Conclusive lower or broken predecessor: rejected. Unavailable required object: indeterminate. Never lower high-water state or replace the accepted chain. |
| Freeze | Expired state, offline valid-until crossing, replayed reaffirmation, subtractive expiry restoration, or publication before all clearances and barriers. | Stale required state: indeterminate. Conclusive replay or bypass: rejected. Preserve the prior transaction, time floor, freeze evidence, and barriers. |
| Mix-and-match | Cross manifest, signature envelope, release envelope, state head, root branch, product, channel, purpose, profile, selector, or artifact; publish a pointer before closure. | Contradictory signed references: rejected. Missing closure: indeterminate or refresh-unavailable. Never commit a partial graph. |
| Equivocation | Two valid successors, alternating channel or pointer views, first-use single view versus returning-client dual view, and fork-capacity exhaustion. | Observed valid conflict: indeterminate or refresh-conflict. Retain both branches and choose neither. Do not assert detection for an unseen first-use split view. |
| Key retention | Skipped root generation, missing predecessor archive, only one transition signature, missing old-root certification, activation mismatch, old-root or old-signer use after cutover, pre-retirement historical use, and unknown cutoff. | Invalid or unauthorized continuity/current use: rejected. Missing closure or unknown cutoff: indeterminate. Complete bounded old evidence may be attributed-historical only. Never install or reactivate an unproven key. |
| Extension ambiguity | Unknown critical, permitted noncritical, duplicate, conflict, criticality downgrade, or extension-defined core authority. | Unknown required semantics: indeterminate. Permitted noncritical: otherwise unchanged result. Downgrade, conflict, or smuggling: rejected. Never install implicit semantics. |
| Threshold and scope | Duplicate signature, composite components counted twice, partial composite, unauthorized extra signature, leaf delegation, scope widening, successor certification, or cross-signer publication. | Rejected; no quorum or authority change. Diagnostics distinguish crypto, authority, and the deliberate absence of TUF thresholds. |
| Publication | Compare-and-swap race, failure before pointer promotion, or ambiguous provider effect after a write. | Failure before pointer promotion leaves the predecessor current. A compare-and-swap miss leaves the attempted successor unselected and preserves the observed canonical head. Ambiguous effects require readback and reconciliation; never report success or retry blindly. Immutable uploaded objects grant no authority without conditional pointer promotion. |
| Refresh | Corrupt or lagging mirror, client crash before commit or readback, or authenticated competing successor or canonical-data disagreement. | Refresh reports `unavailable` when required public state cannot be obtained or verified, `conflict` when authenticated views disagree, and `update` or `no-change` only after readback confirms one complete transaction. A crash preserves the prior complete transaction; never commit a partial graph. |
| Initialization | Malformed configured channel class or controller graph; one controller presented as two channels; authenticated subject disagreement; channel equivocation; missing, unreachable, stale, expired, replayed, wrong-attempt, or otherwise unverifiable required channel or time evidence; or non-overlapping accepted time intervals. | Malformed local configuration uses exit class `64`. Missing or unverifiable required evidence is `unavailable`. Authenticated disagreement, discovered controller aliasing or collapse, equivocation, or non-overlap is `conflict`. Every non-positive result leaves no new anchor or partial trusted state; retain conflict evidence across retries. |
| Retained time | A backward wall clock after a committed initialization or refresh. | The clock change has no independent rejection or conflict disposition and changes no retained state. Effective time remains the maximum of wall time and retained highest trusted time. Never lower the floor; let the owning operation apply its normal freshness result or disposition. |
| Admission limits | Oversized object; excessive history, transition, graph depth, archive, extension, fork, or diagnostic count; and exact-limit and one-over-limit cases. | Once frozen, a caller-supplied input beyond a protocol or installed-policy limit is a conclusive policy violation: `rejected`, with no retained-state mutation. Initialization and refresh limits keep those operations' dispositions and exit classes. The downstream freeze must set each exact limit and bind each case to its owning operation. |

Production profiles must structurally reject fixture identities, locators, and artifacts. The Release Trust oracle must not be presented as the official [tuf-conformance](https://github.com/theupdateframework/tuf-conformance) oracle.

## Truthful public statement

> io.nisavid.release-trust/v1 is a distinct, TUF-informed release-admission protocol. It does not implement the mandatory TUF 1.0.36 root, targets, snapshot, or timestamp metadata roles or the TUF client update algorithm, and it is not described by a TUF POUF. Its signed global history, freshness, bootstrap, historical-attribution, and four-result semantics are governed only by the Release Trust specifications and installed profiles. TUF metadata, if ever used as transport, grants no Release Trust authority unless a separately approved redesign changes that boundary.

Do not call accepted objects TUF root, targets, snapshot, or timestamp, and do not claim TUF-conformant, TUF-compatible, or TUF POUF. TUF-informed is accurate with the statement above.

## Downstream obligations

The wire and conformance freeze in [Prototype the conformance and executable-documentation system](https://github.com/nisavid/dotfiles/issues/213) must:

1. freeze the non-TUF protocol identity and cite this TUF 1.0.36 comparison;
2. preserve one authority plane, direct root grants, non-transitive release leaves, subtractive status power, and human positive reaffirmation;
3. freeze exact JCS bytes, closed schemas, SHA-512 addresses, profiles, full fingerprints, OpenPGP packet rules, both RFC 9980 components, exact scopes, and extension criticality;
4. freeze genesis, exact one-step global history, alternating family changes, cross-head equality, predecessor validation, complete closure, compare-and-swap, fork handling, and atomic retained-state commit;
5. specify canonical acquisition separately from side-effect-free admission, with pointers, mirrors, indexes, and locators never granting authority;
6. freeze effective time, signed freshness, rollback, high-water state, conflict retention, historical closure, and manual rebootstrap;
7. set byte, count, history, transition, graph-depth, archive, extension, fork, and diagnostic limits, including exact-limit and one-over-limit tests;
8. implement the complete hostile matrix above with valid semantic negatives and exact state deltas;
9. keep attributed-historical distinct from current, safe, executable, reinstallable, or promotable;
10. let accepted-current reach only the consumer's next protected policy gate, never generic execution authority;
11. separate written specification, disposable fixture passage, component qualification, and production security evidence; and
12. run protocol, client, corpus, security, and documentation review on the same final revision. Any authority, schema, algorithm, freshness, or client-order change makes earlier evidence stale.

The official TUF conformance suite applies only to a future client that actually implements its TUF surface. Expected failures cannot be converted into a conformance claim.

## What would change the result

A TUF redesign would need complete signed root, targets, snapshot, and timestamp subjects; root-declared keys and thresholds; role versions and expiries; sequential full-root updates under old and new thresholds; a consistent-snapshot choice; the TUF client order; and a rule integrating Release Trust history, status, bootstrap, and four results without bypassing TUF.

That changes schemas, signers, cadence, retained state, failure behavior, and who can expand authority. It requires a new human architecture decision and threat review. It is outside this bounded finding.

## Primary sources

- [TUF specification 1.0.36](https://github.com/theupdateframework/specification/blob/v1.0.36/tuf-spec.md): [roles and PKI](https://theupdateframework.github.io/specification/v1.0.36/#roles-and-pki), [document formats](https://theupdateframework.github.io/specification/v1.0.36/#document-formats), [role formats](https://theupdateframework.github.io/specification/v1.0.36/#file-formats-root), [client workflow](https://theupdateframework.github.io/specification/v1.0.36/#detailed-client-workflow), [key migration](https://theupdateframework.github.io/specification/v1.0.36/#key-management-and-migration), and [consistent snapshots](https://theupdateframework.github.io/specification/v1.0.36/#consistent-snapshots).
- [TAP 11: Using POUFs for Interoperability](https://github.com/theupdateframework/taps/blob/master/tap11.md), version 1, Accepted, last modified 2020-07-17.
- [Reference POUF 1](https://github.com/theupdateframework/taps/blob/master/POUFs/reference-POUF/pouf1.md), version 2, Draft, TUF 1.0, reference implementation v0.12.x; format precedent only.
- [TUF client conformance test suite](https://github.com/theupdateframework/tuf-conformance), test-surface context only.
- [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html), [RFC 9580](https://www.rfc-editor.org/rfc/rfc9580.html), and [RFC 9980](https://www.rfc-editor.org/rfc/rfc9980.html).
