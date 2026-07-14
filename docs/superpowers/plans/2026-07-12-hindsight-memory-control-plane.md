# Hindsight Memory Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the repository-owned, fail-closed Hindsight memory controller and produce a read-only, digest-bound migration plan without writing either migration completion signal or mutating live Hindsight state.

**Architecture:** A dependency-free Python package owns canonical JSON, desired-state validation, immutable plans, adapters, the runtime broker, harness rendering, imports, and migration discovery. The `hindsight-memory` CLI is the acceptance seam. Production HTTP access and test fakes implement one adapter protocol; all mutation flows require an exact plan digest, fresh live-state digest, idle operations, a verified rollback bundle, and the matching two-part migration gate when the action is migration-related.

**Tech Stack:** Python 3.11+ standard library, zsh launch wrappers, chezmoi templates, `unittest`, local Unix-domain sockets, Hindsight 0.8.4 HTTP APIs, `hindsight-admin` only through a compatibility-gated subprocess adapter.

## Global Constraints

- `chezmoi apply` renders inactive desired state only; it never calls Hindsight APIs, starts hooks, downloads models, authenticates providers, or prunes state.
- No credential value, profile token, control-plane key, signing key, memory payload, or private deployment-catalog literal may enter Git, plans, process arguments, or content-free logs.
- Plans bind the inventory digest, resolved-artifact digest, profile, endpoint identity, expected live-state digest, operations snapshot, compatibility results, and ordered actions.
- Ordinary apply is non-destructive. Delete, prune, canonical-ID replacement, import, migration, model activation, and archive retirement are separate plan kinds.
- Migration mutation requires both `distillation-complete.marker` and a matching `## Migration complete` proposal-log entry, plus an independently approved immutable mutation plan.
- This tranche must not create either completion-gate half and must not invoke a live mutating adapter method.
- Public acceptance tests observe the CLI, adapter protocol, rendered files, Unix socket, or content-free ledger; they do not assert private implementation details.
- The initial compatibility floor is Hindsight API and Embed 0.8.4, OptiQ 0.2.15, and mlx-lm 0.31.3.

---

### Task 1: Canonical desired state and immutable plan core

**Files:**
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/__init__.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/canonical.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/model.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/inventory.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/planning.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/ledger.py`
- Create: `home/private_dot_local/bin/executable_hindsight-memory`
- Create: `tests/test_hindsight_memory_controller.py`

**Interfaces:**
- Produces: `canonical_bytes(value) -> bytes`, `digest(value) -> str`, `load_inventory(path) -> Inventory`, `build_plan(inventory, live_state, operations) -> Plan`, `verify_plan(plan) -> None`, and CLI commands `validate`, `plan`, and `status`.
- Consumes: JSON desired state whose root contains exactly `schema_version`, `machine`, `archetype`, `profiles`, `providers`, `banks`, `harnesses`, `migration`, and `policy`.

- [x] **Step 1: Write the failing CLI tests**

  Add tests that invoke `python3 home/private_dot_local/bin/executable_hindsight-memory --state-dir <tmp> validate --inventory <fixture>`, reject unknown/missing keys and duplicate IDs, and assert that two semantically identical inventories produce the literal known SHA-256 of their canonical JSON. Add a plan test whose expected JSON contains `schema_version`, all required bound digests, the target endpoint identity, an idle operations snapshot, compatibility results, ordered actions, `destructive: false`, and `plan_digest`.

- [x] **Step 2: Run the focused test and prove red**

  Run: `python3 -m unittest tests.test_hindsight_memory_controller -v`

  Expected: FAIL because `executable_hindsight-memory` and the package do not exist.

- [x] **Step 3: Implement canonicalization, closed-schema validation, domain records, and planning**

  Use `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()` as the sole canonical encoding. Parse every digest-bearing JSON input with duplicate-key rejection and non-finite-number rejection. Define frozen dataclasses for `BankRef`, `EndpointIdentity`, `OperationSnapshot`, `Action`, `Plan`, and `Inventory`. Validate exact root keys, integer `schema_version == 1` without accepting booleans, unique IDs, bank references, provider role references, profile authority, one authoritative engineering write bank when engineering memory is enabled, derived/overridden port collisions, provider placement/data-class compatibility, and migration artifact/proposal paths. Serialize plans without `plan_digest`, hash that body, then add `plan_digest`; verification recomputes it and uses `hmac.compare_digest`. The executable bootstraps the managed sibling `lib` directory before importing the package so direct `python3` invocation is self-contained.

- [x] **Step 4: Implement content-free ledger and CLI acceptance seam**

  Write JSONL records containing only schema version, action/correlation IDs, bank references, policy/artifact digests, decision, reason code, timestamp, and reversible record ID. Reject payload-like keys recursively. Make `validate` print the resolved inventory/artifact digests, `plan` write canonical JSON with mode `0600`, and `status` report desired/live/plan digest agreement without mutation.

- [x] **Step 5: Run focused and existing contract tests**

  Run: `python3 -m unittest tests.test_hindsight_memory_controller -v`

  Run: `zsh tests/hindsight-memory-control-plane-prd.zsh`

  Expected: PASS, with no changed file outside Task 1 paths.

- [x] **Step 6: Commit the vertical slice**

  Commit literal Task 1 paths with: `feat(hindsight/controller): add immutable desired-state planning`

### Task 2: Fake, HTTP, and migration adapter contracts with guarded apply

**Files:**
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/adapters.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/http_adapter.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/migration_adapter.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/reconcile.py`
- Create: `tests/test_hindsight_memory_adapters.py`

**Interfaces:**
- Consumes: `Plan`, `Inventory`, and `Adapter.snapshot()` from Task 1.
- Produces: `Adapter` protocol, `FakeAdapter`, `HttpAdapter`, `AdminMigrationAdapter`, `create_rollback_bundle()`, and `apply_plan(plan, adapter, approval_digest, gate) -> ApplyResult`.

- [x] **Step 1: Write one red contract test per observable operation**

  Exercise the same suite against `FakeAdapter` and an in-process HTTP fixture: schema/version discovery, endpoint identity, config/stats/tags/scopes/documents/models/directives/operations reads, template dry-run/export/import, config patch, model/directive upsert, document transfer, invalidated-memory inventory/reapply, and bank deletion. Assert bearer-token headers are present on data-plane requests, absent from exceptions and recordings, and `401` is preserved as an authentication failure.

- [x] **Step 2: Write red apply-safety tests**

  Prove apply refuses a wrong approval digest, live-state drift, non-idle operations, missing rollback bundle, failed disposable restore proof, destructive action in an ordinary plan, missing migration gate, and endpoint-identity drift. Prove a failed postcondition triggers rollback and that rollback failure returns an operator-blocked result with activation disabled.

- [x] **Step 3: Implement the adapter protocol and fakes**

  Keep read and mutation methods explicit. `FakeAdapter` records method names and redacted metadata only. `HttpAdapter` uses a dedicated `urllib.request` opener with ambient proxy use disabled, redirects rejected before credentials can reach another hop, and an explicit default TLS context with certificate and hostname verification. It accepts only loopback or inventory-approved TLS endpoints, a bearer-token resolver callback, bounded timeouts, strict JSON size limits, and exception redaction. It never accepts a token in its constructor serialization or a plan. Cover proxy, redirect, and TLS verification failures.

- [x] **Step 4: Implement the compatibility-gated admin adapter**

  Accept a trusted absolute `hindsight-admin` executable, immutable file-identity binding, argv factory, and runner seam. Execute a version/identity probe before use, then revalidate the binary identity before every operation. Run from a fixed trusted working directory with a minimal allowlisted environment. Permit only exact `export-bank`, `import-bank`, `backup`, and `restore` argv shapes rooted at that executable; reject shell strings, relative or replaced binaries, unknown versions, missing archive digests, and absent disposable restore evidence. Never accept direct SQL or database credentials.

- [x] **Step 5: Implement guarded apply and automatic rollback**

  Revalidate the immutable plan and approval digest, refetch endpoint/live/operations state, require the action-specific rollback bundle, apply actions in order, verify each postcondition, restore on the first failure, and append payload-free ledger records. Migration gate parsing must require matching run ID and artifact digest in both gate halves.

- [x] **Step 6: Run and commit**

  Run: `python3 -m unittest tests.test_hindsight_memory_adapters -v`

  Run: `python3 -m unittest discover -s tests -p 'test_hindsight_memory*.py' -v`

  Expected: PASS.

  Commit literal Task 2 paths with: `feat(hindsight/controller): add guarded adapter reconciliation`

### Task 3: Runtime broker and one-use session capabilities

**Files:**
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/broker.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/server.py`
- Create: `tests/test_hindsight_memory_broker.py`

**Interfaces:**
- Consumes: resolved bank routes, policy/artifact digests, `Adapter`, ledger, and a signing-key resolver.
- Produces: JSON-RPC Unix-socket server plus `session mint`, `session exchange`, `session close`, `recall`, `mental_model_fetch`, `checkpoint`, `retain_outcome`, `reflect`, and `session_status` CLI clients.

- [x] **Step 1: Write red broker contract tests**

  Through a temporary Unix socket, assert socket mode `0600`, bounded one-use envelope expiry, atomic staged-handle deletion, concurrent exchanges redeem one handle once and return the same stored capability, signed capability binding, monotonic sequence enforcement, action-ID replay rejection, idempotent writes, digest/revocation/method/route checks, fixed home bank, no caller-supplied raw endpoint/token/bank destination, and payload-free diagnostics.

- [x] **Step 2: Write red availability and retain-ordering tests**

  Assert recall/model-fetch timeout returns no memory plus a visible diagnostic, retain returns a durable queued watermark without blocking, transcript replacements serialize by bank/document, only newer epoch/checkpoint watermarks apply, retry is idempotent, and close reports undrained work after its bounded final checkpoint.

- [x] **Step 3: Implement HMAC-signed opaque envelopes and capabilities**

  Use random 256-bit nonces and keys, canonical JSON claims, HMAC-SHA256, constant-time verification, wall-clock expiry, and persisted used/revoked nonce digests. Serialize one-use check-and-mark across processes with a shared lock and commit it through mode-`0600` atomic replacement plus file and containing-directory `fsync` before returning a capability. Signing material never leaves the broker.

- [x] **Step 4: Implement versioned JSON-RPC routing**

  Parse newline-delimited requests with a fixed maximum size. Resolve routes from the capability and inventory, dispatch only the stable method allowlist, redact diagnostics, and return schema/action/policy/artifact digests plus bounded disposition/payload. Serialize checkpoint writes per `(bank_ref, document_id)`.

- [x] **Step 5: Run and commit**

  Run: `python3 -m unittest tests.test_hindsight_memory_broker -v`

  Expected: PASS.

  Commit literal Task 3 paths with: `feat(hindsight/broker): add scoped runtime sessions`

### Task 4: Disabled harness rendering and reversible activation

**Files:**
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/harnesses.py`
- Modify: `home/private_dot_hindsight/codex.json.tmpl`
- Modify: `home/private_dot_hindsight/claude-code.json.tmpl`
- Modify: `home/private_dot_hindsight/cursor.json.tmpl`
- Create: `tests/test_hindsight_memory_harnesses.py`

**Interfaces:**
- Consumes: resolved harness bindings and broker socket path.
- Produces: minimal broker-only configurations, owned-key manifests, `render_harnesses()`, `activation_plan()`, and `rollback_activation()`.

- [x] **Step 1: Write red renderer tests**

  Start from fixtures containing unknown harness-owned keys. Assert rendering preserves them, changes only declared owned keys, emits no raw Hindsight URL/bank/token, leaves hooks and automatic writes disabled, and records exact pre-activation owned values for rollback.

- [x] **Step 2: Implement minimal disabled renderers**

  Replace direct API/bank output with schema version, broker socket locator, adapter identity, and `active: false`. Preserve unknown settings and registrations through a merge at the rendered-target seam. Do not make `chezmoi apply` activate any adapter.

- [x] **Step 3: Implement separate digest-bound activation plans**

  Activation requires unchanged inventory/artifact/policy digests, healthy broker/profile, adapter self-test, and exact owned-key pre-state. Rollback restores those owned values and disables the adapter on any post-check failure.

- [x] **Step 4: Run and commit**

  Run: `python3 -m unittest tests.test_hindsight_memory_harnesses -v`

  Run: `chezmoi --source home execute-template < home/private_dot_hindsight/codex.json.tmpl | python3 -m json.tool >/dev/null`

  Expected: PASS, with rendered artifacts inactive and token-free.

  Commit literal Task 4 paths with: `feat(hindsight/harnesses): render inactive broker bindings`

### Task 5: Bank policy, provider compatibility, benchmark, and airlock boundaries

**Files:**
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/policy.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/providers.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/benchmark.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/airlock.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/control_server.py`
- Create: `home/private_dot_config/hindsight-memory/benchmark-schema.json`
- Create: `home/private_dot_config/hindsight-memory/synthetic-benchmark.jsonl`
- Create: `tests/test_hindsight_memory_policy.py`
- Create: `tests/test_hindsight_memory_benchmark.py`
- Create: `tests/test_hindsight_memory_airlock.py`
- Create: `tests/test_hindsight_memory_control_server.py`

**Interfaces:**
- Consumes: resolved profile/provider/bank archetypes, private catalog digests, benchmark cases, and broker routes.
- Produces: closed tag/scope policy, engineering/personal/airlock bank specifications, provider compatibility results, benchmark reports, airlock launch plans, and authenticated loopback control endpoints.

- [x] **Step 1: Write red bank-policy tests**

  Assert the exact engineering and personal missions, dispositions, entity-label values, global/contextual model caps and source rules, disabled native refresh schedules, closed tag vocabulary, one semantic scope per retain, selector precedence, projection-only routine cross-bank writes, Memory Defense settings, and disabled native body-bearing audit/LLM tracing. Assert transient state, credentials, tool traffic, injected memory blocks, and recently reversed conventions cannot become durable policy input.

- [x] **Step 2: Implement immutable bank and routing policy**

  Resolve public archetypes plus the authenticated private catalog into a policy artifact whose public serialization contains only disclosure-safe IDs and digests. Enforce exactly one authoritative engineering write bank when enabled, explicit personal-session routing, strict contextual selector precedence, and no arbitrary caller-supplied companion bank.

- [x] **Step 3: Write and implement provider compatibility tests**

  Validate independent LLM/embedding/reranking role bindings, placement/data-class authorization, TLS identity for private-remote providers, credential locators without values, readiness/version/license gates, immutable embedding identity for populated storage, explicit revision switching, and visible reranker fallback/disablement. Keep live Claude Code LLM and Jina MLX reranker as current state; represent GPT-5.3 Codex Spark and MemReranker only as blocked desired candidates until their named adapter/benchmark gates pass.

- [x] **Step 4: Write and implement deterministic benchmark evaluation**

  Parse schema-versioned synthetic/private cases, compute Recall@20 and nDCG@10 from independently supplied relevance judgments, bootstrap deterministic confidence intervals from a recorded seed, enforce must-recall and must-not-return gates, and report latency/cost/memory/model-footprint/provider/license dimensions plus the Pareto frontier. Promotion must require no material retrieval regression or leakage failure and at least one meaningful gain.

- [x] **Step 5: Write and implement airlock plan validation**

  Through a fake OrbStack runner, require a fresh isolated Linux machine, disabled macOS integration and host/peer networking, explicit read-only inputs and narrow output, root-owned egress enforcement, an unprivileged no-sudo harness, tamper/reachability probes, independent profile/token/session state, chunk-only retention with observations/consolidation/models disabled, no core-bank recall, and verified encrypted export plus immediate ephemeral teardown. Host GUI harnesses must remain non-airlock-capable.

- [x] **Step 6: Write and implement the authenticated control service**

  Bind only `127.0.0.1` or `::1`, require an independent access-key resolver on every UI/control request, reject missing/wrong keys and proxy-derived authentication, cap request/response sizes, and expose only health, redacted status, plan inspection, and broker session operations. Prove successful responses cannot reveal data-plane tokens or signing material.

- [x] **Step 7: Run and commit**

  Run: `python3 -m unittest tests.test_hindsight_memory_policy tests.test_hindsight_memory_benchmark tests.test_hindsight_memory_airlock tests.test_hindsight_memory_control_server -v`

  Expected: PASS.

  Commit literal Task 5 paths with: `feat(hindsight/policy): add secure bank deployment policy`

### Task 6: Deterministic import and onboarding clients

**Files:**
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/importing.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/onboarding.py`
- Create: `home/dot_agents/skills/hindsight-memory-import/SKILL.md`
- Create: `home/dot_agents/skills/hindsight-memory-onboarding/SKILL.md`
- Create: `tests/test_hindsight_memory_importing.py`
- Create: `tests/test_hindsight_memory_onboarding.py`

**Interfaces:**
- Consumes: curated Codex files, Claude files, or portable Markdown/JSONL manifests and controller planning/apply APIs.
- Produces: canonical import projections, coverage records, resumable state, digest-bound import plans, and one-question-at-a-time onboarding decisions.

- [x] **Step 1: Write red import projection tests**

  Assert stable IDs from source locator plus source-native identity, timestamps, exact line/file provenance, deterministic closed-vocabulary tags, intended scope, relationship hints, and exactly one coverage disposition per source item. Assert reordered input yields the same projection digest, malformed or secret-like items fail closed, and resume skips only items whose identity and digest match.

- [x] **Step 2: Implement inspect/project/validate/plan/reconcile**

  Keep novelty/duplicate/conflict/omission decisions as proposals. The import client may inspect and create plans in this tranche, but its `apply` path must use the controller gate and therefore cannot mutate without later exact approval.

- [x] **Step 3: Write and implement onboarding decision tests**

  Assert one decision at a time, two to four mutually exclusive choices, recommendation first and labeled, no timeout, plain-prompt fallback, content-free decision log, and coverage of machine archetype, profiles, providers, credentials, banks, harnesses, models, activation, and import. Persist only non-secret desired choices; official login flows are returned as explicit operator actions.

- [x] **Step 4: Write thin agent-facing skills**

  Both skills must call the controller workflow rather than bypassing plans. The onboarding skill must use the user-input widget when present and wait indefinitely for Ivan's answer. The import skill must stop before apply until an exact digest-bound plan is approved.

- [x] **Step 5: Run and commit**

  Run: `python3 -m unittest tests.test_hindsight_memory_importing tests.test_hindsight_memory_onboarding -v`

  Run: `zsh tests/public-agent-skills.zsh`

  Expected: PASS.

  Commit literal Task 6 paths with: `feat(hindsight/import): add planned memory ingestion`

### Task 7: Read-only migration discovery and immutable shadow plan

**Files:**
- Create: `CONTEXT-MAP.md`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/CONTEXT.md`
- Modify: `home/private_dot_local/bin/executable_hindsight-memory`
- Modify: `home/private_dot_local/lib/hindsight_memory_control_plane/__init__.py`
- Modify: `home/private_dot_local/lib/hindsight_memory_control_plane/adapters.py`
- Modify: `home/private_dot_local/lib/hindsight_memory_control_plane/http_adapter.py`
- Create: `home/private_dot_local/lib/hindsight_memory_control_plane/migration.py`
- Modify: `tests/test_hindsight_memory_adapters.py`
- Create: `tests/test_hindsight_memory_migration.py`
- Create at execution time outside Git: `<migration-artifact-directory>/controller-discovery-<UTC timestamp>/inventory.json`
- Create at execution time outside Git: `<migration-artifact-directory>/controller-discovery-<UTC timestamp>/shadow-plan.json`

**Interfaces:**
- Consumes: read-only adapter, source/candidate bank references, approved offline package manifest, migration paths, adapter retain watermarks, and private catalog digests.
- Produces: `discover_migration_state()`, high-water manifest, invalidation/candidate coverage records, redacted semantic diff, and a plan containing no approved mutation authority.

- [x] **Step 1: Write red discovery completeness tests**

  Using the fake adapter, require endpoint/provider identity, versions, config, stats, scopes, tags, documents, models, directives, operations, hooks, schedules, document IDs/update times/content digests, retain watermarks, and invalidated-memory item/source/reason/content digests. Missing required surfaces must make planning incomplete rather than silently empty.

- [x] **Step 2: Write red shadow-plan gate tests**

  Assert exact source/candidate coverage dispositions, one normalized semantic scope per retain, no legacy observations, invalidation disposition/reapplication, candidate provenance/curation digests, idle operations, rollback requirements, explicit cutover freeze/catch-up/restart-on-drift rules, separate closeout and archive-retirement actions, and `approved: false`.

- [x] **Step 3: Implement read-only discovery and proposed planning**

  Allow only adapter read methods. Require one adapter-provided generation or transaction snapshot to cover the full discovery window; if the adapter cannot provide one, require separately verified quiescence evidence and otherwise fail closed. Keep before/after drift comparison as an additional check, not the consistency primitive. Store content-bearing discovery under the external migration artifact directory with mode `0700` directories and `0600` files; plans contain digests and redacted counts, not memory content. Bind the approved offline package digest without copying the package into Git.

- [x] **Step 4: Run fake/disposable tests**

  Run: `python3 -m unittest tests.test_hindsight_memory_migration -v`

  Expected: PASS and fake adapter mutation-call count `0`.

- [ ] **Step 5: Execute read-only live discovery**

  Run the CLI with the live profile explicitly selected and `migration discover --read-only`. Bind the full read to one adapter generation or transaction snapshot, or require separately verified quiescence for the whole window. Before and after, snapshot the two completion-gate halves, bank stats, operation IDs, document high-water marks, and adapter watermarks. Require exact equality for all mutation-sensitive state as an additional drift check. Do not run `apply`, retain, consolidate, refresh, import, config patch, template import, curation reapply, or delete.

- [x] **Step 6: Commit code and tests, not generated migration artifacts**

  Commit literal Task 7 repository paths with: `feat(hindsight/migration): add read-only shadow planning`

### Task 8: Service integration, disposable-stack validation, security review, and closeout publication

**Files:**
- Modify: `home/private_dot_local/bin/executable_hindsight-memory`
- Modify: `home/private_dot_local/lib/hindsight-embed-stack.zsh.tmpl`
- Modify: `home/private_dot_local/bin/executable_hindsight-embed-service`
- Modify: `home/private_dot_local/bin/executable_hindsight-embed-supervisor`
- Modify: `home/Library/LaunchAgents/com.hindsight.embed.stack.plist.tmpl`
- Modify: `home/private_dot_config/hindsight-memory/benchmark-schema.json`
- Modify: `docs/HINDSIGHT.md`
- Create: `tests/hindsight-memory-controller.zsh`
- Modify: `tests/test_hindsight_memory_migration.py`

**Interfaces:**
- Consumes: controller CLI/server, configured profile identity, and an inactive broker policy with no installed data routes.
- Produces: machine-global broker lifecycle, additive profile/fleet status, stable existing five operator commands, and documented approval/rollback boundaries.

- [x] **Step 1: Write red service acceptance tests**

  Assert existing `install/start/stop/status/logs` help remains stable, controller/broker status is additive, LaunchAgent binds control/UI to loopback, managed config contains no tokens, disabled harness render survives `chezmoi apply`, and supervisor logs contain no payloads or credentials.

- [x] **Step 2: Integrate the broker without activating harnesses**

  Extend the supervisor to own the broker and enabled profiles, preserve bounded shutdown, and report endpoint/profile/broker health. Keep existing profile runtime current; no provider/model switch belongs to this tranche.

- [x] **Step 3: Run the complete repository test matrix**

  Run: `python3 -m unittest discover -s tests -p 'test_hindsight_memory*.py' -v`

  Run: `zsh tests/hindsight-memory-controller.zsh`

  Run: `zsh tests/hindsight-memory-control-plane-prd.zsh`

  Run: `zsh tests/private-hindsight-memory-control-plane-prd.zsh`

  Run: `zsh tests/hindsight-embed-stack.zsh`

  Expected: PASS.

- [ ] **Step 4: Run disposable Hindsight and PostgreSQL contract smoke tests**

  Start a disposable Hindsight 0.8.4 profile and database using task-local state and unique loopback ports. Verify authenticated schema/config/template/model/directive/document/operation/curation reads; execute mutations only against the disposable bank; create encrypted rollback exports; restore each data-bearing export into a fresh disposable bank; run `hindsight-admin` full-bank export/import and full-schema backup/restore; and verify invalidated-memory counts/digests survive. Destroy the disposable state after capturing content-free results. Do not point any smoke command at the live profile or migration banks.

- [ ] **Step 5: Run security and broad code review until clean**

  Review authentication boundaries, capability replay/expiry, symlink and path traversal, file modes, canonical digest binding, TOCTOU/drift checks, rollback completeness, subprocess argv safety, HTTP size/time limits, secret/payload logging, template inactivity, and migration-gate enforcement. Fix every critical or important finding and rerun affected tests before declaring the cycle clean.

- [ ] **Step 6: Create the final task-owned checkpoint**

  Audit the index and worktree, commit only Task 8 paths and any review fixes with `feat(hindsight): integrate memory control plane`, and rerun the full test/review gate against the immutable commit.

- [ ] **Step 7: Publish with exact CAS and hand back**

  Use `checkpointing-and-publishing-git-work`'s planner, exact immutable source SHA, explicit full ref, and exact lease. Post-verify the remote SHA and PR state. Hand back the read-only inventory and proposed shadow-plan digests, all unresolved compatibility/credential/catalog decisions, and the exact later approval needed for the completion signal and live mutation. Do not create either completion-gate half and do not mutate live Hindsight.
