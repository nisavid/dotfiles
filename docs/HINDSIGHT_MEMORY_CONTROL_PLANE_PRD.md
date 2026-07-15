# Hindsight Memory Control Plane PRD

## Problem Statement

The managed Hindsight setup is a sound single-profile service, but it does not
yet express the memory system that should be portable across Ivan's machines
and agent harnesses. Profile, bank, provider, runtime, and harness concerns are
collapsed into one flat configuration record. Bank missions and policies live
outside chezmoi. The tracked client files are shallower than the live Codex,
Claude Code, and Cursor integrations. Provider versions and model compatibility
are not reconciled as desired state.

This makes the current system difficult to reproduce, inspect, or evolve
safely. Applying chezmoi can erase useful live adapter settings, while changing
an embedding model or bank policy can silently require a data migration. The
existing migration helpers are one-off tools rather than a reusable import and
reconciliation surface. Hindsight's native bank isolation also does not, by
itself, enforce cross-bank routing, prompt-injection boundaries, or a common
policy across harnesses with different hook capabilities.

The desired result is a long-lived, cross-harness memory system that preserves
unexpectedly transferable engineering knowledge, supports explicitly personal
memory, isolates hostile work in short-lived airlocks, and remains deployable
on machines with different local and hosted inference capacity. It must keep
live state, credentials, and irreversible mutations outside ordinary
`chezmoi apply`.

## Solution

Build one desired-state Hindsight control plane around a versioned machine
inventory. Chezmoi owns non-secret configuration, controller code, bank
archetypes, provider catalogs, harness policies, validation schemas, and
disabled rendered artifacts. A separate controller owns live reconciliation
through `validate`, `plan`, `status`, `apply`, and explicit prune and migration
operations.

The inventory composes runtime profiles, provider role bindings, bank
instances, harness bindings, and policy overlays. A runtime profile is a
process, database, provider, and endpoint isolation boundary. A bank is a
lifecycle, trust, or audience boundary. Repository and workflow knowledge stay
inside the comprehensive engineering bank through deterministic tags,
observation scopes, and explicitly declared mental models.

Trusted sessions retain one stable logical transcript series plus separate
outcome records. They use global recall, two compact engineering models, and at
most one explicitly matched contextual playbook. Personal sessions use a
separate bank and automatically receive only a compact personal profile. Hostile
tasks run in an isolated OrbStack machine containing an ephemeral profile whose
bank stores searchable chunks without extracting or consolidating durable
beliefs.

The controller presents one normalized policy to Codex, Claude Code, Cursor,
and future harnesses. Native integrations may differ internally, but they must
satisfy the same routing, boundedness, provenance, loop-hygiene, failure, and
activation contracts. Harnesses receive only controller-wrapped memory tools;
raw Hindsight bank selection remains an implementation detail.

## User Stories

1. As Ivan, I want one versioned inventory per machine, so that the deployed
   memory topology is reviewable and reproducible.
2. As Ivan, I want to select a named deployment archetype with sparse
   overrides, so that common machines are easy to configure without hiding
   provider choices.
3. As Ivan, I want hardware and credential probes to validate desired state
   without rewriting it, so that configuration remains deterministic.
4. As Ivan, I want each runtime profile to declare providers, models, ports,
   authentication references, and lifecycle policy, so that independent
   runtimes cannot collide silently.
5. As Ivan, I want one fleet supervisor to own the control service and all
   enabled profiles, so that launchd ownership stays simple.
6. As an operator, I want the existing install, start, stop, status, and logs
   commands to remain available, so that the familiar service interface is
   preserved.
7. As an operator, I want profile-specific and fleet-wide status, so that I can
   distinguish a single profile failure from a supervisor failure.
8. As an operator, I want profile ports derived from persisted slots with
   explicit overrides, so that endpoints are stable and collisions fail
   validation.
9. As Ivan, I want provider definitions reused by explicit role bindings, so
   that LLM, embedding, and reranking constraints are modeled separately.
10. As Ivan, I want embedding model identity treated as migration-class state,
    so that a vector-space change cannot be applied in place.
11. As Ivan, I want LLM failover to be declared independently from embedding
    identity, so that generation availability does not corrupt stored vectors.
12. As Ivan, I want reranker fallback to be explicit and visible, so that a
    quality degradation never looks like the selected configuration.
13. As Ivan, I want stable hosted API keys resolved from the macOS Keychain, so
    that credential values never enter chezmoi, templates, plans, or logs.
14. As Ivan, I want OAuth state established interactively for one machine and
    profile, so that rotating credential stores are never synchronized as
    dotfiles.
15. As an operator, I want an OAuth credential-file change to require profile
    reload, so that a daemon cannot continue using invalidated in-memory state.
16. As an operator, I want one refresh-owning process per OAuth home, so that
    concurrent profiles cannot race one token family.
17. As Ivan, I want each profile inventory to support zero or more engineering
    and other bank instances while the default archetype designates at most one
    ordinary engineering authority per machine, so that topology stays flexible
    without creating split-brain history.
18. As Ivan, I want routine engineering recall to remain global, so that a
    seemingly unrelated prior lesson can still be useful.
19. As Ivan, I want repository and workflow identity to enrich provenance and
    model selection without becoming routine recall barriers.
20. As Ivan, I want a first-class optional personal bank, so that explicitly
    personal sessions can remember durable preferences, goals, commitments,
    relationships, routines, logistics, and non-work projects.
21. As Ivan, I want personal memory to exclude external inbox, calendar, drive,
    health, financial, and regulated-record ingestion in the first release, so
    that the privacy surface stays bounded.
22. As Ivan, I want the session home bank selected from machine policy,
    workspace mapping, or explicit session override and then fixed, so that a
    classifier cannot redirect a growing transcript.
23. As Ivan, I want unmapped sessions to default to engineering, so that
    ordinary development work has a predictable home.
24. As Ivan, I want prompt-level routing to admit relevant companion recall
    without moving the session transcript, so that cross-domain context remains
    possible without collapsing bank boundaries.
25. As Ivan, I want a trusted reviewer to admit policy-allowed cross-bank recall
    and minimal projections, so that useful personal and engineering context
    can cross safely when relevant.
26. As Ivan, I want deterministic deny rules to run before model review, so
    that secrets, excluded sensitive categories, raw tool output, and recalled
    memory blocks never cross a bank boundary.
27. As Ivan, I want every automatic cross-bank action announced with source,
    target, action, and correlation ID, and every write to include an
    independently reversible record ID, so that invisible sharing cannot
    accumulate.
28. As Ivan, I want projections to be minimal, idempotent, provenance-linked,
    auditable, and independently deletable, so that they do not become hidden
    transcript copies.
29. As an agent user, I want each trusted session to retain a stable logical
    transcript series at meaningful checkpoints and close, so that memory is
    durable without reprocessing every turn or losing pre-compaction topics.
30. As an agent user, I want clean task outcomes retained separately from the
    transcript, so that verified results remain easy to recall without storing
    raw tool traffic.
31. As Ivan, I want source, harness, canonical repository, controlled workflow,
    and lifecycle tags to be deterministic, so that recall and reconciliation
    do not depend on content classification.
32. As Ivan, I want session, branch, worktree, and other volatile identifiers in
    metadata rather than tags, so that observation scopes do not fragment.
33. As Ivan, I want each retain to contribute to exactly one semantic
    observation scope, so that consolidation cost and duplicate beliefs remain
    bounded.
34. As Ivan, I want a canonical repository scope when repository identity is
    reliable and one global active scope otherwise, so that local patterns and
    cross-domain knowledge both have coherent homes.
35. As Ivan, I want LLM-emitted knowledge kinds to support investigation and
    mental-model sourcing without granting authority, so that classification
    errors cannot change policy.
36. As an agent user, I want routine recall around 10,000 tokens and an explicit
    deep path around 20,000 tokens, so that normal context stays balanced while
    broad synthesis remains available.
37. As an agent user, I want routine responses to use recall plus direct mental
    model fetches, so that expensive `reflect` loops are not hidden in every
    prompt.
38. As Ivan, I want `reflect` to remain explicit, cited, and audited, so that
    high-authority synthesis is visible and intentional.
39. As an engineering agent, I want a compact operator profile on every trusted
    session, so that settled communication, scope, review, and publication
    rules are consistently available.
40. As an engineering agent, I want a compact transferable engineering
    principles model, so that tested design, debugging, testing, and operations
    lessons orient work across repositories.
41. As an engineering agent, I want at most one explicitly matched repository
    or workflow playbook, so that useful specialization does not crowd out
    global context.
42. As an engineering agent, I want no contextual model when source-tag
    coverage or selection is uncertain, so that a guessed or empty playbook is
    never elevated.
43. As a personal-session agent, I want only a compact personal profile injected
    automatically, so that relationships, commitments, and logistics are
    recalled only when the prompt needs them.
44. As Ivan, I want mental models refreshed on staggered, change-aware
    schedules with health and queue gates, so that freshness does not recreate
    the prior quota and operation backlog.
45. As Ivan, I want mental-model refreshes to exclude mental models as source
    evidence, so that summaries cannot recursively launder themselves into
    facts.
46. As Ivan, I want an explicit trust mode at session start and policy-forced
    airlocks for configured high-risk sources, so that hostile data is isolated
    before retention.
47. As an airlocked agent, I want a reviewed static bootstrap of transferable
    engineering and security principles, so that I retain safe guidance without
    reaching the live core bank.
48. As Ivan, I want airlock text stored as searchable chunks with extraction and
    observations disabled, so that hostile instructions are not synthesized
    into durable beliefs.
49. As Ivan, I want an airlock to produce an encrypted audit export and
    source-cited bridge candidates, so that useful lessons can be reviewed
    without automatic promotion.
50. As Ivan, I want a verified airlock bank deleted immediately after closeout,
    so that hostile data has no unnecessary live retention window.
51. As a Codex user, I want prompt-specific ambient recall and safe checkpoint
    retention, so that Codex benefits from memory without recursive ingestion.
52. As a Claude Code user, I want prompt-specific ambient recall and compatible
    transcript lifecycle handling, so that compaction does not erase prior
    topics.
53. As a Cursor user, I want session-start ambient context plus agentic memory
    tools, so that outcome parity does not require an unsupported hook cadence.
54. As a future Hermes user, I want memory disabled until its adapter declares
    and proves required capabilities, so that an unaudited integration does not
    receive ambient retention.
55. As Ivan, I want unknown harness-owned settings preserved during rendering,
    so that enabling managed memory does not erase unrelated configuration.
56. As Ivan, I want rendered hook artifacts disabled until an approved
    controller activation, so that `chezmoi apply` cannot begin recall or
    retention.
57. As an operator, I want activation bound to an immutable digest and endpoint,
    bank, and capability checks, so that reviewed artifacts are the ones that
    become active.
58. As Ivan, I want one `hindsight-memory session` entry point for home-bank and
    trust-mode selection, so that launch-time policy is consistent across CLI
    and GUI harnesses.
59. As Ivan, I want Codex, Claude, and portable Markdown/JSONL import adapters,
    so that prior memory sources can be reconciled without one-off scripts.
60. As Ivan, I want every import item assigned a stable identity, timestamp,
    provenance, and coverage disposition, so that imports are resumable,
    reviewable, and reversible.
61. As Ivan, I want heuristic novelty and deduplication to propose rather than
    apply outcomes, so that imports remain digest-bound approval artifacts.
62. As Ivan, I want the deferred raw Codex corpus mined only for novel durable
    information, so that the comprehensive bank gains evidence without a noisy
    bulk import.
63. As an operator, I want onboarding to guide inventory, provider, bank,
    harness, and import choices one decision at a time, so that setup remains
    understandable on different machines.
64. As an operator, I want onboarding to install declared local dependencies and
    establish credentials without bypassing controller plans, so that
    convenience does not weaken mutation gates.
65. As Ivan, I want model recommendations earned on a private, human-vetted
    local retrieval benchmark, so that model cards and hosted-teacher agreement
    do not become the quality authority.
66. As Ivan, I want model promotion to require no material retrieval regression,
    no leakage failure, and at least one meaningful quality, latency, cost, or
    memory gain, so that recommendations represent real improvement.
67. As Ivan, I want the private benchmark content to remain outside Git and move
    only through explicit encrypted export/import, so that real queries and
    judgments are not published with dotfiles.
68. As a contributor, I want synthetic fixtures, evaluator code, schema, and the
    private dataset digest tracked, so that benchmark mechanics remain
    reproducible without private content.
69. As an operator, I want every live reconcile to take a rollback export,
    verify idle operations, show a redacted diff, and verify post-apply state,
    so that bank changes are transactional and reviewable.
70. As Ivan, I want unmanaged state reported and pruned only by a separate
    export-backed operation, so that ordinary reconcile is non-destructive.
71. As Ivan, I want the legacy engineering bank rebuilt through a verified
    shadow bank, so that old observation scopes are normalized without direct
    database edits.
72. As Ivan, I want the historical candidate bank deleted in the approved
    migration closeout after verified reconciliation, so that an obsolete
    archive does not become a permanent second authority.
73. As a maintainer, I want the one-off cleanup and database migration helpers
    removed after the migration gate closes, so that normal runtime code no
    longer carries obsolete machinery.
74. As Ivan, I want content-bearing native audit and LLM trace storage disabled,
    so that personal and confidential prompts are not duplicated into
    operational tables.
75. As Ivan, I want a content-free controller ledger retained for 90 days, so
    that cross-bank and mutation decisions remain traceable without preserving
    memory payloads.
76. As Ivan, I want every Hindsight data-plane endpoint protected by a distinct
    profile bearer token held only by the controller, so that a harness cannot
    bypass bank policy by calling loopback directly.
77. As an agent user, I want each session to receive an expiring,
    replay-resistant controller capability, so that memory access remains bound
    to the approved home bank and trust mode.
78. As Ivan, I want airlocked CLI agents to run in isolated OrbStack machines,
    so that hostile shell actions cannot reach host memory state, Keychain
    credentials, or the core Hindsight token.
79. As Ivan, I want each machine's ordinary engineering bank to remain its one
    local authority, so that provider profiles cannot create hidden writable
    replicas or split-brain history.
80. As a harness integrator, I want one versioned authenticated runtime broker
    contract for session, recall, retain, model, reflect, and close operations,
    so that adapters cannot infer security or failure behavior independently.
81. As an operator, I want canonical bank references to include profile and
    endpoint identity, so that the same bank ID in two runtimes is never
    ambiguous.
82. As an operator, I want canonical cutover to freeze writes, catch up to a
    recorded source watermark, and use restore-tested artifacts, so that a
    non-atomic bank-ID replacement cannot lose accepted memory.
83. As Ivan, I want candidate reconciliation manifests bound through the final
    shadow archive into the canonical bank, so that neither obsolete live bank
    can be deleted before accepted evidence and curation state are verified.
84. As Ivan, I want migration artifacts retained until a separate digest-bound
    retirement approval, so that live-bank closeout cannot silently remove
    rollback or provenance evidence.
85. As Ivan, I want organization-specific model IDs, repository tags, and legacy
    aliases held in an encrypted deployment catalog, so that the public work
    contract remains reviewable without publishing private deployment context.

## Implementation Decisions

### Domain model

- A **machine inventory** is the non-secret desired state for one host.
- A **deployment archetype** is a versioned set of profile, provider, bank, and
  harness defaults. A host chooses it explicitly and may apply sparse
  overrides.
- A **runtime profile** is one Hindsight process, database, provider universe,
  and endpoint set. It is not a topic or harness.
- A **provider definition** describes one concrete inference endpoint, model,
  authentication mode, compatibility contract, and license gate.
- A **role binding** assigns provider definitions independently to LLM,
  embedding, and reranking roles.
- A **bank reference** is the tuple of profile ID, immutable endpoint identity,
  and bank ID. Controller plans, capabilities, routes, projections, notices,
  and ledgers use the full reference even when a bank ID is unique today.
- A **bank archetype** defines reusable missions, dispositions, labels, models,
  directives, defense rules, and controller policy.
- A **bank instance** materializes a composed archetype inside one runtime
  profile and declares lifecycle and authority.
- A **harness binding** maps one harness to a controller endpoint, home-bank
  policy, adapter, and required capabilities.
- A **session envelope** is the signed, one-use launch-time choice of home bank
  reference and trust mode. Those fields are immutable after consumption.
- A **projection** is a minimal derived record retained into a non-home bank. It
  is never a full transcript copy and is the only routine automatic cross-bank
  write between policy-compatible trusted banks.
- A **bridge artifact** is a reviewed, source-cited promotion package for an
  airlock or cross-machine transfer. It is not the mechanism for routine trusted
  companion recall or projection.
- Each profile may declare zero or more engineering and other bank instances.
  When a machine enables ordinary engineering memory, exactly one bank reference
  is authoritative for those writes. Other profiles may serve different
  providers or trust classes but cannot become peer-writable replicas.
  Cross-machine movement is an explicit, operator-approved bridge export/import
  operation; there is no routine synchronization.

### Desired-state ownership and controller

- Chezmoi owns schemas, non-secret inventory, provider and model catalogs,
  bank-archetype fragments, overlay definitions, controller code, harness
  adapter policy, disabled hook artifacts, tests, and documentation.
- `chezmoi apply` renders desired artifacts but never calls Hindsight mutation
  APIs, starts ambient memory hooks, downloads models, logs in providers, or
  prunes state.
- The controller exposes `validate`, `plan`, `status`, and `apply` as its stable
  reconciliation interface. Destructive retirement, prune, migration, import,
  model install, and activation are explicit subflows built on the same plan
  contract.
- A plan binds the inventory digest, resolved artifact digest, target profile,
  target endpoint identity, expected live-state digest, operations snapshot,
  compatibility results, and proposed actions. Apply accepts only that
  immutable plan and fails on drift.
- Every live apply requires idle affected operations and an adapter-appropriate
  rollback bundle before mutation. The bundle contains the pre-state digest,
  endpoint identity, encrypted and digested exports or active-file snapshots,
  restore procedure, and retention state; data-bearing exports must pass a
  disposable restore test. The plan presents a redacted semantic diff. Apply
  verifies every postcondition and automatically restores the pre-state on any
  failed action or post-check. An incomplete restore is an operator-blocked
  incident and leaves activation disabled.
- Ordinary apply is non-destructive. Undeclared banks, models, directives,
  profiles, and adapter settings are reported. Deletion requires an explicit
  export-backed prune plan.
- Hindsight bank-template import is one adapter operation, not the complete
  archetype contract. Hindsight 0.8.4 does not include `memory_defense` in the
  bank-template schema or `enable_auto_consolidation` in the template config,
  and template imports do not remove absent models or directives. The
  reconciler applies and verifies those surfaces separately.
- Production uses the Hindsight HTTP adapter. Tests use an in-memory/fake
  adapter implementing the same controller-facing contract.
- Canonical-ID replacement and full-bank rollback use a separate,
  compatibility-gated PostgreSQL migration adapter around the supported
  `hindsight-admin export-bank` and `import-bank` commands. Ordinary reconcile
  never receives direct database credentials, and no adapter issues ad hoc SQL.
- Every profile enables Hindsight's API-key tenant extension. Its distinct
  bearer token is resolved only into the fleet controller and profile process.
  Harnesses and browsers never receive a data-plane token.
- The Hindsight control-plane service and UI bind only to loopback and require an
  independent machine-local control-plane access key. That key is distinct from
  every profile token, is never placed in rendered browser files or persistent
  logs, and is checked on every UI and control endpoint. An unauthenticated or
  header-stripping reverse proxy is invalid desired state.

### Private deployment catalog

- The private deployment catalog is source-only age ciphertext with no managed
  plaintext target. The controller decrypts it only in memory or inside a
  protected ephemeral phase during validation and planning. Plans bind its
  ciphertext and resolved-content digests but never include its plaintext.
- Catalog schema version 1 requires the integer `schema_version` value `1` and
  has exactly six top-level fields: `schema_version`, `contextual_models`,
  `contextual_model_migrations`, `repository_catalog`, `workflow_catalog`, and
  `privacy`. Booleans, floats, unknown versions, unknown or missing keys,
  duplicate identities, invalid tag forms, and dangling references fail closed
  before rendering, planning, or mutation.
- Each `contextual_models` entry has exactly `id`, `selector_tag`, and
  `source_filter_tags`. Model IDs and selector tags are unique. The selector and
  every source-filter tag reference a canonical repository or controlled
  workflow declared by the same catalog; source filters are non-empty and
  duplicate-free.
- Each `contextual_model_migrations` entry has a unique `source_id`, a
  `disposition`, and a disposition-dependent `target_id`. `retain` requires a
  target identical to the source; `supersede` requires a distinct target;
  `retire` forbids a target. The public v1 engineering target-model roster for
  this resolution is exactly `operator-profile`, `engineering-principles`, and
  `review-pr-playbook`; a private target must also be declared in
  `contextual_models`. Every target resolves in that combined roster before
  cutover, and every migration source ID and private successor ID is
  disclosure-guarded through `privacy.public_forbidden_literals`.
- `repository_catalog` has exactly `canonical`, `aliases`, and `drop_aliases`.
  Canonical values match `repo:<canonical-slug>` and are unique. Mapped aliases
  target a canonical value; drop aliases remove the repository tag; the mapped
  and dropped source sets are disjoint from each other and from the canonical
  set. `workflow_catalog` has exactly one duplicate-free `controlled` list whose
  values match `workflow:<canonical-slug>`.
- `privacy` has exactly `public_forbidden_literals`. That duplicate-free list
  covers every private model ID, every migration source ID and private successor
  ID, selector, source-filter tag, repository value, mapped or dropped alias,
  and controlled workflow value. Keyed validation
  rejects any listed literal in the public PRD. Publication validation scans
  every newly reachable public blob across every range commit tree, including
  merge results and type changes, rather than only ordinary per-parent diffs or
  the working-tree copy. No filename suffix creates an exemption: age-named
  blobs are scanned as bytes, while the catalog is separately required to
  decrypt and authenticate with the configured identity.

### Runtime broker contract

- The machine-global control service includes a versioned runtime broker. Host
  adapters use JSON-RPC over a user-only Unix-domain socket; airlock adapters
  use an equivalent socket inside their isolated machine. The broker has no
  unauthenticated TCP listener, and socket permissions do not replace session
  capability validation.
- `hindsight-memory session` asks the broker to mint a signed, opaque, one-use
  envelope with a bounded expiry. CLI launches receive an envelope handle
  through their initial environment. GUI launches receive a user-only staged
  envelope artifact in the controller runtime directory. Exchange atomically
  consumes and deletes the handle; the signing key never leaves the broker.
- Exchange returns a short-lived session capability bound to the session ID,
  harness, home bank reference, trust mode, companion policy, policy digest,
  artifact digest, issue time, expiry, and revocation ID. Each request carries
  that capability, a unique action ID, a monotonic request sequence, and an
  idempotency key for writes. The broker rejects replay, sequence rollback,
  expiry, revocation, digest drift, method expansion, and bank-route expansion.
- The stable methods are session exchange and close, bounded recall, direct
  mental-model fetch, transcript checkpoint, outcome retain, explicit reflect,
  and session status. Adapters never submit a profile URL, data-plane token,
  bare bank ID, or destination bank. The broker resolves every route from the
  capability and policy.
- Responses contain schema version, action ID, policy and artifact digests,
  disposition, bounded payload, and content-free diagnostics. They never expose
  a raw profile endpoint, data-plane token, signing material, or unrestricted
  bank reference.
- Session exchange and activation fail closed. Recall and model-fetch timeout or
  unavailability return no memory plus a visible diagnostic and do not block the
  prompt. Retains enqueue asynchronously, expose a durable watermark and retry
  state, and never block a user response. Explicit reflect returns a bounded
  error rather than stale synthesis. Close attempts the final checkpoint within
  a declared timeout and reports any undrained retain for recovery.

### Fleet lifecycle

- One per-user LaunchAgent owns one fleet supervisor.
- The supervisor reconciles the machine-global control service and every
  enabled profile, including local provider sidecars declared by those
  profiles.
- The existing five operator commands remain stable. Profile selection and
  fleet-wide status are additive.
- Each persisted profile slot derives stable API, UI, and declared sidecar
  ports. The fleet broker and supervisor control endpoint are machine-global,
  not profile-slot ports. Explicit overrides are allowed; any collision is a
  validation error.
- Profile health includes process ownership, endpoint identity, API version,
  database readiness, provider readiness, configured bank readiness, sidecar
  compatibility, and credential-generation freshness.
- An authenticated health gate proves that missing and incorrect data-plane
  tokens receive `401` and that the controller reaches only the profile bound
  into its immutable plan.
- A separate control-plane health gate proves loopback-only binding, rejects
  missing and incorrect UI access keys, rejects an unauthenticated proxy path,
  and confirms that successful UI access cannot reveal a profile bearer token.
- Hindsight API and Embed 0.8.4, OptiQ 0.2.15, and mlx-lm 0.31.3 form the initial
  compatibility floor. Upgrades are explicit plans with contract tests.

### Provider catalog and deployment archetypes

- Provider roles are independent. LLM bindings may declare ordered failover.
  Embedding identity is immutable for populated storage and changes only
  through a blue-green rebuild. Reranking may use an explicitly declared
  fallback or become visibly disabled.
- Every provider declares placement as `local`, `third-party-hosted`, or
  `private-remote`; the data classes it may receive; transport and API
  compatibility; TLS server identity and trust roots where applicable;
  authentication locator; readiness probe; timeout; and no-payload-log
  contract. Private-remote providers fail closed on TLS, identity, or readiness
  drift.
- The initial catalog supports four baseline topology archetypes: fully hosted;
  hosted LLM plus OpenAI embedding plus local reranking; hosted LLM plus local
  embedding and reranking; and fully local. These are sparse defaults, not
  provider bundles. Any role in any archetype may instead bind to an approved
  private-remote provider, and a machine may publish a private-remote overlay;
  every role remains independently placeable within machine policy.
- Retain extraction, observation consolidation, mental-model refresh, reflect,
  cross-bank routing, and cross-bank review inherit the profile LLM binding by
  default. An archetype may override each subrole only with an explicit provider
  binding and data-class authorization; inheritance and overrides appear in the
  resolved plan.
- Supported hosted LLM authentication includes `openai-codex` with an explicitly
  selected Codex model and reasoning effort, and `claude-code` with an explicitly
  selected Claude model and reasoning effort. Other hosted services require
  Keychain API-key references.
- Hosted retrieval candidates include Jina embedding and reranking, OpenAI
  `text-embedding-3-small` plus Jina reranking, and ZeroEntropy embedding and
  reranking. Their readiness includes endpoint, terms, license, and benchmark
  gates.
- Hindsight 0.8.4 reaches hosted Jina embeddings through its OpenAI-compatible
  embedding client and hosted Jina reranking through its Cohere-compatible
  reranker client. The catalog records those wire contracts rather than naming
  a nonexistent first-class Jina embedding provider.
- Local reranking candidates include the default CPU model,
  `nisavid/mxbai-rerank-large-v2-mlx-4bit`, KaLM Reranker V1 Small 4-bit,
  MemReranker 4B 4-bit, and license-gated zerank-2.
- Local retrieval candidates include the default CPU pair; BGE-M3 4-bit with
  KaLM Reranker V1 Small 4-bit; BGE-M3 8-bit with MemReranker 4B 4-bit; and the
  license-gated zembed-1 plus zerank-2 pair.
- Fully local candidates include Qwen3.6 35B A3B 4-bit with BGE-M3 16-bit and
  MemReranker 4B 8-bit, and a license-gated zembed-1 plus zerank-2 variant.
- Catalog order records Ivan's current preference hypothesis, not a quality
  claim. Only the local benchmark may promote a combination to recommended.
- A catalog candidate without an exact artifact ID, serving contract, license
  disposition, or compatibility result remains non-activatable even when its
  family appears in an archetype.
- Apple-silicon local models use MLX when available and OptiQ when compatible.
  Model artifacts stay in the local model cache and are never committed or
  encrypted into chezmoi.
- Model IDs may track their upstream latest revision, but only an explicit plan
  resolves a new immutable revision, runs compatibility and retrieval gates,
  records the active revision locally, switches atomically, and retains the
  prior cached revision for rollback. Service restarts never update models.

### Current-machine target

- The ordinary engineering and personal banks share one authenticated runtime
  profile. Canonical bank references plus session capabilities provide the
  audience boundary; harnesses cannot reach either bank through the raw profile
  endpoint.
- The selected desired LLM is `openai-codex` with GPT-5.3 Codex Spark at the
  desired reasoning effort `xhigh`. Hindsight 0.8.4 currently maps that setting
  only to detailed reasoning summaries and does not send
  `reasoning.effort="xhigh"`. Activation therefore requires a tested provider
  adapter change that sends the intended payload; until it passes, the live
  Claude Code LLM remains current state.
- Embeddings remain `text-embedding-3-small` through a dedicated, file-backed
  `openai-codex` login. The OAuth home is machine-local, is never copied, and is
  owned by one profile process.
- The selected desired reranker candidate is
  `nisavid/MemReranker-4B-OptiQ-4bit` through stock `optiq serve` plus a loopback
  Cohere-compatible controller adapter. Ivan's target selection does not make a
  quality claim; it becomes recommended or activatable only after the private
  benchmark and compatibility gates pass.
- The adapter derives the model's affirmative and negative token IDs from the
  installed tokenizer, performs one-token log-probability scoring, preserves
  document order, caps concurrency, exposes health and version metadata, and
  fails the quality/latency gate rather than silently changing models.
- The first reranker fallback is
  `nisavid/mxbai-rerank-large-v2-mlx-4bit` through the same OptiQ service and
  adapter. Direct mlx-lm serving is available only if the OptiQ wrapper fails
  compatibility checks. Every fallback is explicit-plan-only and visibly
  degraded.
- The live Claude Code LLM and Jina MLX reranker remain current state until an
  approved post-migration plan changes them. Candidate state is never presented
  as already active.

### Credential policy

- Chezmoi stores authentication modes and non-secret locators only. It stores no
  provider credential value, including in age-encrypted files.
- Stable API keys use per-machine macOS Keychain items. The fleet resolves them
  directly into child-process environments without rendering them into files,
  plans, process arguments, or logs.
- OAuth onboarding uses the provider's official interactive login. Codex OAuth
  homes force file-backed credential storage, are independently logged in, and
  are never initialized by copying another `auth.json`.
- The controller fingerprints credential-file generation metadata, not token
  content. A generation change makes the profile stale and requires a reload.
- An OAuth home may have only one active refresh-owning process. Concurrent
  profiles require independent OAuth state, an API key, or local inference.
- Each profile data-plane token and the controller's session-envelope signing
  key are independent machine-local secrets. The controller mints a single-use
  envelope and exchanges it for a short-lived session capability containing the
  fixed home bank reference, trust mode, allowed companion policy, policy and
  artifact digests, nonce state, issue time, and expiry. It rejects replay,
  expiry, digest mismatch, and caller-supplied bank expansion.

### Engineering bank archetype

- Extraction mode is concise. Observations and free-form entity extraction are
  enabled. Disposition is skepticism 4, literalism 3, empathy 2.
- The retain mission extracts durable engineering knowledge from trusted
  user/assistant conversations and structured outcome records: explicit
  preferences and corrections, approval boundaries, settled team and workflow
  conventions, product and technical decisions with rationale and trade-offs,
  reusable procedures, failure chains from symptom through verified fix, and
  relationships among people, repositories, systems, issues, pull requests,
  releases, clusters, and tools. It preserves provenance and time. It treats
  branch, review, deployment, cluster, service, provider, and quota state as
  dated evidence requiring live verification. It ignores greetings, unchosen
  brainstorming, session and tool bookkeeping, raw tool output, secrets,
  credentials, opaque volatile identifiers, transient local paths, recalled
  memory blocks, and unsupported assumptions.
- The observations mission synthesizes durable cross-domain operating rules,
  preferences, design principles, recurring failure patterns, tested runbooks,
  causal chains, and corrections. It preserves evolution and distinguishes
  settled, provisional, and contradicted claims. It does not promote current
  state, pending proposals, one-off accidents, or agent mechanics into standing
  belief.
- The reflect mission identifies the bank as Ivan's shared engineering memory
  across approved harnesses. It treats memory as fallible evidence rather than
  authority, prefers current instructions and verified live state, distinguishes
  durable rules from dated state, cites uncertainty and provenance, never
  infers authorization, and answers tersely and directly.
- The optional `kind` entity label has the values `rule`, `principle`,
  `runbook`, `decision`, `incident`, `state`, and `reference`. It is emitted as
  a tag for investigation and model sourcing. It is never used for security,
  authorization, home-bank selection, or automatic promotion.
- The global `operator-profile` model summarizes user-authored engineering
  rules, communication preferences, evidence expectations, scope and approval
  boundaries, delegation, Git and review behavior, checkpoint and publication
  policy, settled corrections, and known rationale. It excludes current state,
  secrets, and unconfirmed conventions and is capped at 1,536 tokens.
- The global `engineering-principles` model summarizes tested, transferable
  design, debugging, testing, operations, release, and collaboration lessons,
  including conditions, counterexamples, and failure modes. It distinguishes
  user rules from inferred heuristics, excludes current state and mechanics,
  and is capped at 2,048 tokens.
- Both global models use delta refresh, exclude all mental models as source
  evidence, include raw facts and observations, and have both native
  `refresh_after_consolidation` and `refresh_cron` disabled. The controller is
  the only refresh scheduler.
- Contextual overlays use strict, controlled repository or workflow source tags
  and remain disabled until the shadow rebuild proves adequate tag coverage.
  Organization-specific model IDs, selectors, source filters, and migration
  dispositions come only from the encrypted private deployment catalog.
- Global models are untagged. Each contextual model carries its one canonical
  selector tag for reflect visibility and uses a strict source filter or an
  explicit tag-group expression for refresh. The controller fetches selected
  models directly by stable ID; an unscoped reflect cannot see contextual
  models accidentally.
- A session receives the two global models and at most one contextual model.
  Explicit workflow selectors outrank repository selectors; equal-priority or
  uncertain matches inject no contextual model.
- The migration disposition map is exact: `operating-profile` is superseded by
  `operator-profile`; organization-specific contextual models use the
  disposition in the private deployment catalog; `review-and-pr-playbook` is
  superseded by `review-pr-playbook`; `project-context` has no successor; and
  `engineering-principles` is new. Old models remain available but uninjected
  until source coverage, content equivalence, and target fetch checks pass. Only
  then may a prune plan retire superseded models. Current project state comes
  from prompt-specific recall and live inspection.

### Personal bank archetype

- Extraction mode is concise. Observations and free-form entity extraction are
  enabled. Disposition is skepticism 4, literalism 3, empathy 4.
- The retain mission applies only to explicitly personal sessions. It extracts
  durable preferences, goals, commitments, relationships, recurring routines
  and logistics, non-work project decisions, and corrections while preserving
  attribution, time, confidence, and provenance. It treats schedules, travel,
  location, and task status as dated. It excludes credentials, authentication
  material, health, medical, financial, legal, and regulated details, raw
  external-app content, unnecessary third-party private facts, pleasantries,
  agent mechanics, and recalled memory blocks.
- The observations mission synthesizes durable preferences, recurring routines,
  relationship context, long-lived goals, commitment patterns, and their
  evolution. It minimizes third-party detail, keeps claims attributed,
  distinguishes confirmed commitments from tentative ideas, and never turns
  dated logistics into standing truth.
- The reflect mission identifies the bank as Ivan's private personal memory for
  explicitly personal sessions. It personalizes only when relevant, minimizes
  disclosure, distinguishes stale logistics from current facts, never infers
  consent or authority, and permits personal content to influence engineering
  only through the controller's reviewed cross-bank policy.
- The optional personal `kind` label includes `preference`, `goal`,
  `commitment`, `relationship`, `routine`, `logistics`, `project`, `state`, and
  `reference`. It supports retrieval only and is not a sensitivity classifier.
- The `personal-profile` model contains user-confirmed durable preferences,
  routines, values, and assistance style. It excludes relationships,
  commitments, current logistics, third-party private facts, credentials, and
  excluded sensitive categories. It is capped at 1,024 tokens, uses delta
  refresh, and excludes mental models as evidence.
- `personal-profile` is the only personal mental model injected automatically.
  Other personal context is retrieved for the current prompt.

### Airlock archetype

- Every executable airlock runs in a newly created OrbStack isolated Linux
  machine created with both macOS-integration isolation and network isolation.
  The CLI harness, controller broker, ephemeral Hindsight profile, database, and
  any local sidecars run inside that boundary. Host GUI harnesses never execute
  this flow.
- The security claim is limited to OrbStack's isolated-machine contract;
  OrbStack machines share a Linux kernel and are not represented as independent
  VMs. A task whose threat model requires a separate guest kernel or hypervisor
  boundary fails closed until another reviewed backend is available.
- The machine has no automatic macOS integration. Only explicitly declared task
  inputs are copied or mounted, read-only unless the plan grants a narrower
  writable output path. Host Keychain, SSH agent, profile state, Hindsight
  state, home directories, and container sockets are unavailable.
- Network policy blocks host IPs and other OrbStack machines while preserving
  only the explicitly approved external provider and source access needed by
  the task. OrbStack host and peer isolation is verified before launch; a
  root-owned broker namespace and egress service then restrict external
  destinations.
- The hostile harness runs as a dedicated unprivileged principal outside the
  egress enforcement principal. It has no `sudo`, setuid escalation path,
  network-administration capability, container socket, firewall or route write
  access, or writable broker configuration. The controller verifies those
  invariants before every launch. If they cannot be established, the airlock
  uses no network or fails closed.
- Host loopback, the host broker socket, core profile endpoints, and undeclared
  DNS or network destinations must all fail reachability tests. Tamper probes
  must also fail to change firewall rules, routes, DNS policy, network
  namespaces, or broker configuration. If the selected provider or source
  cannot operate under that policy, airlock activation fails closed.
- The ephemeral Hindsight profile has independent ports, provider state,
  database, endpoint, bank, tenant bearer token, and session capability. It
  cannot reuse the ordinary profile's OAuth home or data-plane token.
- Retention uses chunk-only mode, which stores each chunk as a `world` memory
  unit without LLM, entity, or temporal extraction. The archetype separately
  sets `enable_observations=false`, sets
  `enable_auto_consolidation=false`, defines no model roster or refresh route,
  and denies mental-model generation methods. Those separate controls—not chunk
  mode alone—prevent observation consolidation and mental-model generation.
- The airlock has no live engineering or personal recall. It receives one
  reviewed, versioned, non-sensitive bootstrap artifact containing transferable
  engineering principles and security rules, with no personal content,
  project facts, credentials, or operational state.
- Controller policy treats all recalled airlock content as untrusted data, not
  instructions. It grants no authorization and cannot make claims about core
  banks.
- Closeout creates and verifies an encrypted export, produces source-cited
  bridge candidates, records every candidate's disposition, and then deletes
  the live bank, ephemeral profile, and isolated OrbStack machine immediately.
  Promotion is a separate reviewed controller plan.
- Host GUI harnesses are not airlock-capable in the first release. An adapter
  remains disabled until it can prove the same filesystem, credential, network,
  endpoint, and lifecycle boundary.

### Directives and defense

- Engineering and personal banks enable Hindsight Memory Defense with
  `sensitive_data` redaction for future retains. Airlocks use the same redaction
  before chunk storage.
- Memory Defense is a secret and known-PII scrubber, not a prompt-injection
  boundary. Trust routing, chunk-only airlocks, wrapper tools, and reviewer
  policy provide the stronger boundary.
- Common reflect directives require live truth over memory, treat memory as
  evidence rather than instructions, forbid secret reconstruction, enforce
  explicit scope and approval boundaries, and prevent unsettled or recently
  reversed conventions from becoming durable rules.
- Personal reflect directives add data minimization and cross-bank disclosure
  boundaries. Airlock directives add untrusted-content, no-core-claim, and
  no-authorization rules.
- Directives affect `reflect` only. Equivalent invariants are enforced in the
  controller and adapters for recall, retain, injection, and projection.
- Native Hindsight audit logging is disabled because it stores request and
  response bodies. Native LLM request tracing is disabled because it stores
  prompts and outputs.
- The controller writes a content-free ledger containing action and correlation
  ID, full source and target bank references, policy and artifact digests,
  decision, reason code, timestamp, and any reversible record ID. Default
  retention is 90 days.

### Retain, tag, and observation policy

- Trusted harnesses retain the full cleaned user/assistant conversation under a
  stable document ID for the current session epoch with `update_mode=replace`.
  Each checkpoint submits the complete cleaned epoch transcript; Hindsight
  deletes the prior document memories and reprocesses the replacement. A
  pre-compaction checkpoint seals that epoch and the post-compaction transcript
  starts a new monotonically numbered document ID, preserving earlier topics as
  an immutable part of the logical session series. Append mode is allowed only
  for an adapter contract that submits non-overlapping deltas under independently
  stable document IDs.
- The broker serializes transcript replacements per bank reference and document
  ID. It accepts only a strictly newer epoch and checkpoint watermark, rejects a
  delayed older replacement, and makes retries idempotent. Checkpoints occur at
  meaningful-turn intervals, before compaction, at clean task checkpoints, and
  on normal stop or close.
- Raw tool traffic, injected memory blocks, synthetic startup policy, and
  harness bookkeeping are stripped. Sanitized outcome records are retained as
  separate stable documents at clean checkpoints and final close.
- The controller records the last successful retain watermark for crash
  recovery.
- The canonical deterministic tag vocabulary is closed in v1. Harness identity
  preserves the deployed `agent:` namespace with `agent:codex`,
  `agent:claude-code`, and `agent:cursor`. Source values are
  `source:codex-hook`, `source:claude-plugin`, `source:cursor-plugin`,
  `source:manual-note`, `source:file-memory`,
  `source:codex-memory-archive`, `source:portable-import`,
  `source:projection`, and `source:airlock-bridge`. Lifecycle values preserve
  the `scope:` namespace with `scope:active`, `scope:archive`, and
  `scope:airlock`.
- The initial canonical repository values come from the encrypted private
  deployment catalog and each matches exactly `repo:<canonical-slug>`. Initial
  controlled workflow values also come from that catalog and each matches
  exactly `workflow:<canonical-slug>`. New deterministic values require a
  reviewed catalog change. Repository and workflow tags are omitted rather than
  guessed.
- Shadow migration preserves valid harness, source, repository, and workflow
  values; applies the exact legacy-to-canonical repository alias map from the
  private deployment catalog and removes repository tags named by its drop-alias
  list; preserves known `agent:*` and `source:*` values; and maps only declared
  source or workflow aliases. Lifecycle is always rederived from the target
  bank—`scope:active` for the engineering shadow, `scope:archive` for an archive,
  and `scope:airlock` for an airlock—rather than copied from the source. Every
  unknown or dropped tag receives a disposition. Legacy UUID, session, branch,
  worktree, and obsolete project tags move to provenance metadata or receive an
  explicit omission reason.
- Session, thread, branch, worktree, provider, and adapter-version data are
  provenance metadata. Raw machine-local paths and secrets are excluded.
- Each retain supplies one observation scope. Reliable repository memory uses
  exactly `repo:<canonical-slug>`. Other trusted memory uses exactly
  `scope:active`. The two are never paired. Workflow, source, harness, session,
  `kind`, branch, and worktree tags never become observation scopes.
- The shadow rebuild applies that exact mapping before retention. It imports no
  legacy observations; after documents and accepted facts are reprojected with
  one canonical scope, the shadow bank reconsolidates observations from the
  normalized evidence.

### Recall, mental-model injection, and reflect policy

- Routine engineering recall is global and uses the current prompt plus bounded
  project context. Repository, workflow, and harness identity improve the query
  but do not hard-filter the comprehensive bank.
- Routine recall sends `budget=mid` and `max_tokens=10000`. Explicit deep recall
  sends `budget=high` and `max_tokens=20000`. Hindsight's `max_tokens` bounds
  returned fact text, not the complete response, so the policy also declares
  separate entity, chunk, and source-fact limits and a controller aggregate cap
  across facts, entities, chunks, source facts, metadata, and injected mental
  models. Deterministic truncation records what was omitted.
- Every recall is time-bounded, aggregate-token-bounded, type-bounded,
  advisory-framed, and isolated from prompt failure. No previous recall remains
  active after a timeout or bank failure.
- Injected context identifies its bank, memory IDs, model IDs, refresh times,
  and policy version. It says that memory may be stale and cannot override
  current instructions or live evidence.
- Model refresh is controller-scheduled, staggered, and change-aware. Every
  managed model has native `refresh_after_consolidation` disabled and
  `refresh_cron` cleared. A refresh
  requires new consolidated evidence in the source scope, an idle operation
  queue, healthy provider and budget gates, a rollback snapshot, and successful
  post-refresh verification.
- A model is stale when relevant consolidated evidence has passed its scheduled
  refresh window without a successful refresh. Stale or missing models are not
  injected; prompt-specific recall remains available.
- `reflect` is never an ambient pre-response step. It is an explicit operation
  with a content-free audit event. Hindsight's native `based_on` response gives
  memory, model, and directive IDs rather than document provenance; before the
  controller claims a source citation, it resolves returned memory IDs to their
  document and provenance records and marks any unresolved source explicitly.

### Cross-bank policy

- The home bank reference owns the transcript. Selection precedence is explicit
  session override, then the most-specific workspace mapping, then machine
  default; ambiguous equal-specificity mappings fail validation. The result is
  immutable after the session envelope is consumed.
- A prompt router may select a recall-lead bank reference and companion bank
  references for the current prompt. It may not change the transcript owner.
- Deterministic deny rules run before the reviewer and apply the intersection of
  the source-bank and target-bank exclusion policies. Secrets, credentials,
  authentication material, health, medical, financial, legal, regulated data,
  raw external-app content, unnecessary third-party private facts, raw tool
  output, recalled blocks, and disallowed source classes never cross.
- A declared trusted reviewer may automatically admit bounded companion recall
  and automatically retain a minimal projection. If the reviewer is unavailable
  or not approved for both banks, only the cross-bank path fails.
- The inventory binds each reviewer to an inference provider, permitted source
  and target data classes, maximum input and output size, timeout, and
  no-payload-log contract. A reviewer cannot inspect a bank whose data class is
  outside that declaration.
- Projections use stable identities derived from source session, turn range,
  full target bank reference, and policy version. They carry source references,
  not full transcript content, and are independently deletable.
- Every automatic read or projection receives an action/correlation ID and emits
  a concise live notice naming full source and target identities and the action.
  Projection writes additionally name their independently reversible record ID.
  Full content remains in the relevant bank and is not copied into the notice or
  ledger.
- Explicit allow, deny, home-bank, and companion-bank choices override automatic
  routing within the fixed safety policy.

### Harness policy and activation

- The normalized harness contract requires explicit home-bank routing, stable
  document lifecycle, deterministic tags, retain context, source provenance,
  semantic observation scopes, bounded recall, advisory injection, loop
  hygiene, non-blocking retention, failure isolation, model injection, trust
  routing, and visible diagnostics.
- Codex and Claude Code use prompt-specific ambient recall. Cursor uses
  session-start ambient context plus agentic controller-wrapped tools. This is
  accepted outcome parity, not a silent capability gap.
- A native adapter may satisfy a capability directly. Otherwise the controller
  wraps or replaces that capability. Missing required behavior is a validation
  error unless the inventory declares a reviewed exception.
- Ordinary rendering writes complete disabled artifacts into a side-by-side
  inactive staging tree; it never targets active Codex, Claude Code, or Cursor
  integration files. Unknown harness-owned settings and registrations remain
  untouched.
- Every harness has one automatic write bank reference. Companion bank
  references are resolved through controller routing; direct arbitrary bank IDs
  are not exposed.
- `hindsight-memory session` launches CLI harnesses with a signed envelope and
  stages a one-use envelope for GUI harnesses.
- The controller exchanges that envelope for a short-lived capability whose
  methods and bank routes are fixed. Wrapped tools do not accept unrestricted
  profile URLs, bearer tokens, or caller-selected bank IDs.
- Activation snapshots the exact active files and registrations, verifies their
  digests, and semantically merges only declared memory-owned fields from the
  staged artifact. It preserves unknown fields and unrelated registrations.
  Deactivation or rollback restores the exact pre-activation owned values and
  registrations and removes only artifacts created by that activation.
- `chezmoi apply` renders inactive hooks and settings. Activation is a separate,
  reversible controller apply bound to an approved digest, unchanged active
  snapshot, and successful endpoint, bank-reference, capability, and
  loop-hygiene checks.
- Hermes starts with no ambient memory. It needs a capability declaration and
  adapter contract tests before enablement.

### Import and onboarding skills

- The import skill is a thin agent-facing client of the controller. Its first
  adapters cover curated Codex memory files, Claude memory files, and a portable
  Markdown/JSONL manifest.
- Each adapter emits a canonical projection with stable item IDs, source
  timestamps, provenance, relationship hints, deterministic tags, intended
  scopes, and a coverage disposition for every source item.
- Import runs as inspect, project, validate, plan, apply, reconcile, and verify.
  It is resumable, state-tracked, rate-limit-aware, and idempotent.
- Heuristic novelty, duplicate, conflict, and omission judgments are proposals.
  The approved digest-bound plan is the mutation artifact.
- The raw Codex stream receives an offline novelty pass. Only durable information
  absent from the curated corpus is eligible, and every omission has a reason.
- The onboarding skill walks one decision at a time with no timeout. It uses a
  user-input widget when available and a plain prompt otherwise, presents two to
  four mutually exclusive choices with the recommendation first and labeled,
  and persists each answer and rationale in a content-free decision log. It
  covers machine archetype, profiles, provider roles, credentials, banks,
  harness bindings, model roster, activation, and import.
- Onboarding may persist desired state, install declared local dependencies, and
  invoke official login flows. It cannot bypass controller plan and apply gates.

### Retrieval benchmark and model promotion

- Real benchmark queries, judgments, and retrieved private content live under
  Hindsight's private machine-local state. They move only through an explicit
  encrypted export/import operation.
- Git tracks the benchmark schema, evaluator, synthetic fixtures, and private
  dataset digest.
- Human-vetted relevance judgments are the authority. Published benchmarks and
  hosted-provider agreement are supporting evidence only.
- The evaluator reports Recall@20 and nDCG@10 with bootstrap confidence
  intervals, plus separate must-recall and must-not-return gates.
- Results include latency, direct cost, peak memory, model footprint, provider
  availability, compatibility, and license readiness. Each deployment envelope
  reports a Pareto frontier rather than one weighted score.
- A candidate becomes recommended only if it has no material retrieval-quality
  regression, no policy or leakage failure, and at least one meaningful gain in
  quality, latency, cost, or memory.
- Model resolution, installation, benchmark execution, and activation are
  explicit operations. No background or service-start model switching exists.

### Migration and rollout

- The inventory names a configurable external migration-artifact directory and
  proposal log. Source implementation and offline fixtures may proceed while the
  gate is open, but deliberate Hindsight retain, consolidate, model refresh,
  template import, config mutation, or bank deletion requires both
  `distillation-complete.marker` and a matching `## Migration complete` entry in
  the proposal log. The marker and entry must identify the same migration run
  and artifact digest.
- The migration-artifact directory stores the encrypted canonical-source bank
  archive, final shadow-bank archive, full-schema rollback backup, historical-
  candidate provenance archive, and candidate curation manifest with their
  digests, key locators, compatibility metadata, and restore or reapplication
  proofs. These artifacts have no automatic or time-based expiry. They remain
  available until Ivan separately approves a digest-bound archive-retirement
  plan after cutover acceptance, with no unresolved rollback, verification, or
  incident dependency. The plan enumerates each artifact and verifies its
  deletion; live-bank closeout never implies archive-retirement authority.
- Already-active ambient auto-retain remains exempt from the pre-gate moratorium;
  it is existing user-facing behavior, not a migration write. The current
  engineering and historical candidate banks otherwise remain read-only to this
  work until the two-part gate and a separate mutation plan are approved.
- The controller first snapshots endpoint and provider identity, Hindsight and
  adapter versions, config, stats, scopes, tags, documents, models, directives,
  operation state, active hook registrations, and native model schedules. It
  records a source high-water manifest of stable document IDs, update times,
  content digests, and each active adapter's last successful retain watermark.
  It separately inventories Hindsight's invalidated-memory curation archive with
  item, source-document, reason, and content digests because full-bank export
  does not carry that table.
- A shadow engineering bank is rebuilt from every retained source document,
  reconciled historical evidence, and novel approved raw-memory unit. The
  projection applies the exact tag mapping, supplies one semantic observation
  scope per retain, imports no legacy observations, and records a coverage or
  omission disposition for every source item.
- After normalized documents and accepted facts are present, the shadow bank
  consolidates from that evidence and builds the target mental-model roster.
  Native `refresh_after_consolidation` and `refresh_cron` remain disabled. The
  shadow must pass coverage reconciliation, source fidelity sampling, secret
  and leakage checks, operations-idle checks, recall benchmarks, model content
  checks, and rollback verification.
- Every invalidated source memory receives a curation disposition. The shadow
  must prove that excluded or superseded content did not reappear as a valid
  fact, or match the corresponding new fact and reapply the invalidation through
  the supported curation API. An empty invalidation archive or complete,
  verified disposition and reapplication is a destructive-cutover gate.
- Before the shadow can become a cutover source, every historical-candidate item
  receives a coverage or omission disposition, its accepted evidence is
  reconciled into the shadow, and every invalidated candidate memory receives the
  same verified curation disposition and reapplication treatment. The controller
  seals candidate coverage and curation manifests, binds their digests to the
  shadow state, and rejects subsequent candidate or shadow drift. It also creates
  and verifies the candidate's separate encrypted full-bank provenance archive
  and encrypted curation manifest under the migration-artifact retention policy.
- Hindsight 0.8.4 has no bank rename or atomic bank-ID swap. The cutover plan
  therefore declares a bounded maintenance interval. It snapshots and disables
  or redirects every current retain path, blocks new session exchange, revokes
  write methods on existing capabilities, waits for in-flight retains and
  operations to become idle, captures a final source high-water mark, and
  applies a final catch-up to the shadow. Any watermark or digest drift restarts
  verification rather than entering the destructive step.
- After final catch-up and an idle-operation check, the PostgreSQL migration
  adapter creates separate full-bank `hindsight-admin export-bank` archives for
  the canonical source and verified shadow. It encrypts and digests both and
  restore-tests each in a disposable compatibility database under a fresh bank
  ID. The final shadow archive manifest binds the canonical source high-water and
  invalidation manifests, candidate coverage and curation-manifest digests, and
  shadow content digest. The plan records the exact Hindsight and PostgreSQL
  compatibility result. HTTP bank-template export remains only a config/model/
  directive artifact, and HTTP document transfer is not treated as a full-bank
  rollback.
- Because full-bank export omits the invalidated-memory archive, the controller
  also creates an encrypted, digested full-schema `hindsight-admin backup` after
  all profile writes are frozen. It restore-tests that backup in a disposable
  database and verifies the invalidated-memory count and item digests. The schema
  backup is the authoritative rollback artifact for the canonical-ID interval;
  targeted bank exports remain migration and provenance artifacts.
- The authenticated HTTP adapter then deletes the old canonical `engineering`
  bank and verifies its absence while all harness writes remain frozen. The
  supervisor stops the profile API and workers and verifies database maintenance
  exclusivity. With the profile stopped, cutover imports the verified shadow
  archive with the target-bank override set to `engineering`, restarts the
  profile, reapplies and verifies the resolved archetype, clears native model
  schedules, and checks document and fact coverage, regenerated observations,
  model fetches, representative recall, endpoint identity, authentication,
  cold-cache behavior, and the canonical source, candidate coverage, candidate
  curation, and shadow-content digests bound into the archive manifest. Only then
  does the controller mint new session capabilities and reactivate harness
  writes. Pre-cutover capabilities are never rebound to the new policy digest.
- Neither the original shadow nor historical candidate bank may be deleted until
  the canonical bank has passed cutover acceptance with the bound candidate
  evidence and curation dispositions, and the controller has re-read and
  reverified every required archive and restore proof from the external
  migration-artifact directory. Any missing, changed, or unavailable artifact,
  manifest mismatch, or unresolved canonical discrepancy blocks both deletions.
- The original shadow bank remains read-only and has no harness binding or
  capability route during acceptance. After the shared live-bank deletion gate,
  the approved migration closeout deletes it through the authenticated HTTP bank
  API and verifies that only the canonical bank reference is authoritative. Its
  verified full-bank archive remains available under the migration-artifact
  retention policy.
- Failure during the canonical-ID interval keeps every profile write frozen and
  stops the profile. The PostgreSQL migration adapter restores the verified
  pre-change full-schema backup, which removes any partial target and preserves
  invalidated-memory curation state. The controller restarts the normal profile,
  verifies all bank references, the source high-water and invalidation manifests,
  and representative cold-cache recall, and only then restores the prior hook
  registrations. A rollback that cannot re-establish the verified source state
  is an operator-blocked incident, not a partial success.
- After the shared live-bank deletion gate, historical-candidate deletion may
  occur in the approved migration closeout. The controller verifies that the
  canonical bank still matches the bound candidate coverage and curation
  manifests, deletes the candidate through the authenticated HTTP bank API, and
  then proves that the canonical bank and all retained migration artifacts remain
  available and unchanged. There is no live-bank cooling period and no implicit
  archive retirement.
- The one-off single-bank cleanup and direct-database migration helpers are
  removed only after the external gate, canonical cutover, candidate closeout,
  provenance-archive verification, and rollback acceptance are complete.

## Testing Decisions

- The primary acceptance seam is the controller CLI. Tests invoke `validate`,
  `plan`, `status`, and `apply` against temporary machine state and a fake
  Hindsight API, then assert observable artifacts, actions, gates, and final
  state.
- Live-apply acceptance tests require an idle-operation snapshot, encrypted and
  digested adapter-appropriate rollback bundle, disposable restore proof for
  data-bearing state, redacted semantic diff, post-apply verification, and
  automatic pre-state restoration after each injected action or post-check
  failure.
- Tests claim external behavior rather than narrating implementation. They
  assert what the operator, harness, rendered target, endpoint, or ledger sees.
- Pure resolver tests cover inventory composition, sparse overrides, derived
  endpoints, port collisions, profile authority, embedding migration-class
  diffs, model revision resolution, credential locators, bank overlays, and
  deterministic artifact digests.
- Hindsight adapter contract tests cover schema discovery, config reads and
  patches, bank-template dry run and import, model/directive upsert behavior,
  explicit prune, Memory Defense and auto-consolidation verification, operation
  gates, HTTP template export, HTTP document transfer, PostgreSQL full-bank
  export/import, full-schema backup/restore including invalidated memories, and
  endpoint identity. Each test asserts only the state that its selected adapter
  actually carries.
- Runtime broker contract tests cover one-use envelope exchange, staged GUI
  consumption, signature and expiry checks, request sequences, write
  idempotency, capability revocation, method and route bounds, canonical bank
  references, failure isolation, retain recovery watermarks, and payload-free
  diagnostics.
- Harness adapter contract tests cover Codex, Claude Code, and Cursor rendering,
  unknown-field preservation, explicit write-bank selection, stable document
  IDs with replace semantics, semantic scopes, native and aggregate recall
  budgets, loop stripping, model injection, session envelopes, side-by-side
  inactive rendering, semantic activation merge, exact deactivation, and
  activation rollback.
- Private deployment-catalog tests cover fail-closed schema versions and keys,
  unique model and selector identities, selector and filter references, mapped
  and dropped alias dispositions, controlled workflow references, actionable
  retain/supersede/retire semantics, source-only ciphertext handling, protected
  decryption modes and cleanup, merge-result and type-change blob coverage, and
  absence of catalog-classified literals from every new public blob. Adversarial
  fixtures cover committed and untracked plaintext disguised with an age suffix.
- Cross-bank tests cover deny-before-review, reviewer timeout, prompt-scoped
  companion recall, projection idempotency, minimal content, provenance,
  deletion, notices, and content-free audit records.
- Airlock tests cover pre-retain trust selection, ephemeral profile isolation,
  no core endpoint reachability, chunk-only storage, disabled observations and
  models, static bootstrap filtering, export verification, bridge disposition,
  and immediate deletion.
- OrbStack airlock tests prove isolated-machine creation, no automatic macOS
  integration, declared-only mounts, host and peer network isolation, absent
  host credential and state paths, distinct data-plane authentication, scoped
  session capabilities, root-owned egress enforcement, an unprivileged harness
  with no network-administration or escalation path, failed firewall/route/DNS/
  namespace tampering, unreachable host loopback and core endpoints, and machine
  deletion after verified closeout.
- Authentication tests prove tenant-token enforcement on HTTP and MCP, no raw
  token in rendered harness configuration or process arguments, one-use session
  envelopes, capability expiry and replay rejection, and refusal of arbitrary
  bank expansion.
- Control-plane UI tests prove loopback-only binding, independent access-key
  enforcement on every UI/control endpoint, rejection of missing and incorrect
  keys and unauthenticated proxies, token-free rendered files and logs, and no
  browser-visible profile token.
- Import tests use synthetic Codex, Claude, Markdown, and JSONL fixtures. They
  cover stable identity, time ordering, wiki-link relationships, coverage
  dispositions, novelty proposals, resumability, rate limits, digest binding,
  rollback, and payload-free logs.
- Migration tests cover shadow rebuild, legacy-tag normalization, one-scope
  retention, full document coverage, exclusion of legacy observations,
  reconsolidation from normalized evidence, mental-model disposition and native
  schedule clearing, invalidated-memory inventory and curation reapplication,
  source high-water marks, retain-path freeze, final catch-up, profile and worker
  quiescence, database maintenance exclusivity, destructive canonical-ID
  cutover, full-schema rollback with curation preservation, cold-cache restart
  verification, candidate coverage and curation digests bound through the final
  shadow archive into the canonical bank, refusal to delete either live bank
  before that verification, unbound shadow-bank retirement, candidate provenance
  and curation archives, candidate deletion, retained-archive availability after
  each live-bank deletion, explicit archive-retirement approval, and refusal
  while either part of the external completion gate is absent.
- Model adapter tests verify Cohere request and response shape, tokenizer-derived
  scoring token IDs, normalized affirmative probability, stable ordering,
  concurrency bounds, health/version metadata, OptiQ and mlx-lm compatibility,
  explicit fallback, and no automatic switching. Codex provider tests inspect
  the outbound payload and require `reasoning.effort="xhigh"`; summary-detail
  mapping alone fails compatibility.
- Benchmark tests use synthetic public fixtures in CI and validate metric
  calculations, bootstrap intervals, must-recall and must-not-return gates,
  Pareto classification, private-dataset digest checks, and promotion rules.
- Fleet lifecycle tests cover one LaunchAgent, multiple profiles, persisted
  slots, endpoint collisions, process ownership, credential-generation drift,
  sidecar health, bounded waits, token-free logs, and the existing five-command
  interface.
- Chezmoi rendering tests explicitly bind the task worktree's source directory.
  They never fall back to another checkout's source state.
- A disposable real Hindsight/Postgres stack provides a smaller compatibility
  smoke gate for the pinned version. It supplements rather than replaces the
  controller acceptance seam.
- No test mutates the live engineering or candidate bank. Live post-marker
  verification is a separately approved operator runbook.

## Out of Scope

- Live changes to the engineering or historical candidate bank before the
  external distillation completion gate.
- Team-shared banks, team identity, RBAC, governance, and background promotion.
- Regulated health, payment-card, legal, or other compliance-specific records.
- Gmail, Calendar, Drive, or other personal-source connectors.
- Background cross-machine synchronization or peer-writable bank replicas.
- Scheduled or off-machine disaster-recovery backups. Pre-apply exports are
  transactional rollback artifacts, not backup policy. The historical
  candidate's explicitly required provenance archive is the narrow exception.
- Automatic model revision polling, installation, benchmarking, or activation.
- Ad hoc SQL or direct table rewrites for scope, tag, fact, observation, or
  cutover work. The supported, compatibility-gated `hindsight-admin` full-bank
  migration adapter is not an ad hoc rewrite.
- Changes to OptiQ itself. The control plane owns the protocol adapter.
- Raw Hindsight MCP or API capabilities exposed directly to harness agents.
- Content-bearing native Hindsight audit logging or LLM request tracing.
- Automatic full-transcript routing by content classification.
- Automatic airlock-to-core promotion or indefinite airlock retention.
- A production Hermes ambient-memory adapter before its capability audit.
- Publishing the private benchmark dataset or private memory payloads.

## Further Notes

- The existing single-profile lifecycle module is retained and deepened into a
  fleet runtime. It is not replaced by a second overlapping service manager.
- The current tracked harness files are not authoritative examples of desired
  adapter behavior; live safe settings must be preserved through semantic
  merge and explicit ownership.
- The external migration completion signal remains the authority for lifting
  the bank-mutation moratorium. Source work and offline fixtures do not lift it.
- Bank-template manifests remain generated, reviewable artifacts. This document
  records their source semantics and does not duplicate full generated JSON.
- OrbStack is the forward runtime for new isolated workloads. Existing Podman
  workload discovery, data migration, compatibility repair, rollback, and
  retirement are governed by the companion Podman-to-OrbStack migration PRD
  rather than hidden inside Hindsight apply.
- This repository has no configured issue-tracker publication contract for the
  PRD. The committed document is the durable work contract until an operator
  explicitly authorizes publication elsewhere.
