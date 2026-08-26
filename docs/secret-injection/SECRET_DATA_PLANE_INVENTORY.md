# Current secret data plane inventory

This inventory records the source-controlled process-scoped secret data plane
at [`bff0415`](https://github.com/nisavid/dotfiles/commit/bff0415c7d05e08c8f918cebb8860e9997fee2b1).
It supports [Evaluate replacing secret-exec with pass-cli
run](https://github.com/nisavid/dotfiles/issues/173); it does not decide that
replacement or authorize implementation.

The inventory is value-free. It did not query a host, provider session, vault,
item, or credential value. A validating projection of the encrypted catalog
emitted only syntactically valid profile, variable, command, and profile-binding
names. No locator or decrypted catalog was retained.

## Boundary

The domain glossary distinguishes the **secret data plane**, which resolves one
credential profile and injects it into one consumer process, from the **secret
control plane**, which owns enrollment, inspection, mapping, readiness, and
rotation. The current source divides responsibilities as follows.

| Surface | Classification | Relationship to the data plane |
| --- | --- | --- |
| `secret-exec` | Secret data plane | Validates profiles, scrubs managed names, resolves the selected profile, binds values, and replaces itself with the consumer. |
| AWS credential-process mode | Secret data plane adapter | Resolves the requested profile and emits the narrow AWS credential JSON contract instead of executing a consumer; the managed AWS binding selects `aws`. |
| Credential profile renderers | Secret control plane desired state | Render value-free locators and unset directives into the private input consumed by `secret-exec`. |
| Application overlays and command shims | Consumer adapters | Route declared consumers through one profile; they do not resolve values themselves. |
| `proton-pass-ensure-ready`, startup bindings, and status | Provider lifecycle and readiness | Establish and repair the provider session before a pass-backed launch. |
| `secret-exec-native-store` | Operation-specific bridge | Supplies the bootstrap item to readiness and supplies Linux Secret Service profile lookups to the data plane. |
| Agent Equipment catalog and lock | Secret-free control-plane contract | Model reviewed profile references and wrapped provider routes; they are not runtime resolvers. |
| `secret-exec-migrate` | Legacy migration and retirement | Imports old sources, verifies deployed bindings, and gates removal of ambient plaintext. |

The bootstrap item belongs to provider-session lifecycle, not to a consumer
credential profile. The logged-in operating-system user is the trust boundary;
the system does not claim hostile same-user isolation.

## Data plane contract

### Startup and profile selection

`home/private_dot_local/bin/executable_secret-exec` is the canonical launcher.
It:

1. starts with fixed `/bin/zsh -f`, disables inherited tracing, and removes an
   inherited Proton bootstrap token before normal execution (lines 1–8);
2. accepts either `secret-exec <profile> -- <command> [args...]` or the narrow
   `secret-exec aws-credential-process <profile>` mode (lines 472–490);
3. requires a real mode-`0700` profile directory and real mode-`0600` profile
   files, validates every profile and directive, and rejects duplicate locator
   mappings for the same name within one profile (lines 298–359); repeated unset
   directives and the same managed name in different profiles use set semantics;
4. loads every profile to build the complete set of managed environment names,
   while selecting locators only from the requested profile (lines 314–360);
5. removes every managed name inherited from the parent, including names not in
   the selected profile (lines 362–369); and
6. runs provider readiness only when the selected profile contains a
   `pass://` locator (lines 371–395).

Loading every profile is part of the isolation contract. A profile with no
public direct caller can still add a name to the global inherited-environment
scrub set.

### Resolution and consumer execution

For each selected binding, `secret-exec`:

- resolves `pass://` through `pass-cli item view`;
- resolves `secret-service://` through the verified sibling
  `secret-exec-native-store` adapter on Linux;
- gives each provider operation a three-second deadline;
- uses a dedicated provider process group, terminates and reaps descendants on
  timeout or wrapper signal, and keeps provider bytes separate from controller
  status and diagnostics;
- rejects missing, empty, multiline, or carriage-return-bearing results; and
- exports the accepted value under its declared environment name.

These responsibilities live in
`home/private_dot_local/bin/executable_secret-exec` lines 79–263 and 397–449.
After resolution, the launcher closes its private diagnostic descriptor and
`exec`s the requested command with its original arguments (lines 498–512).
The final consumer therefore retains ordinary stdin, stdout, stderr, TTY,
signal, and numeric exit behavior. Secret values are not placed in command
arguments or persisted by the launcher.

The AWS mode is an intentional exception to process execution. It requires
exactly the access-key and secret-key bindings, refuses terminal output,
validates their serialization-safe character sets, and emits AWS
`credential_process` version 1 JSON (lines 452–470).

### Current executable discovery

Current `main` already implements the map's settled discovery rule.
`secret-exec`, `proton-pass-ensure-ready`, and `secret-exec-migrate` confirm that
`pass-cli` is discoverable and invoke the literal command name through their
runtime `PATH`. They carry no fixed candidate, package-manager preference,
executable-path override, or separate symlink policy. Ordinary `PATH` semantics,
including an intentionally selected relative or empty component, therefore
apply inside the logged-in-user trust boundary
(`home/private_dot_local/bin/executable_secret-exec` lines 264–289,
`home/private_dot_local/bin/executable_proton-pass-ensure-ready` lines 394–399,
and `home/private_dot_local/bin/executable_secret-exec-migrate` lines 17–34).

The three entrypoints use fixed `/bin/zsh -f`; `secret-exec` and readiness scrub
an inherited bootstrap token before selecting `pass-cli`. Migration separately
requires commands that encode, inspect, or remove plaintext to resolve to
absolute paths through its runtime `PATH` before invoking them. On macOS,
graphical startup derives the readiness process's `PATH` through the bounded
shared `launcher darwin` startup policy. Host qualification must still prove the
actual `PATH`, selected executable, and version in interactive, service,
LaunchAgent, and GUI processes without encoding those paths into repository
behavior.

## Managed profile and command state

`home/.private-secret-exec.toml.age` contains the value-free locators and
command-to-profile mappings. `.privacy-age-envelopes.json` inventories its
exact ciphertext path and digest for structural integrity checks; it is not an
authenticated admission receipt. Protected ciphertext changes depend on the
trusted-base verifier and owner-signed admission boundary described in
`docs/ENCRYPTION.md`. Private templates render the following targets under
`~/.config/secret-exec`.

| Profile | Managed names | Public or generated bindings |
| --- | --- | --- |
| `aws` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | AWS default `credential_process`; `k9s` and `sz` command shims |
| `context7` | `CONTEXT7_API_KEY` | Codex, Claude, and OpenCode; Agent Equipment also declares Cursor |
| `firecrawl` | `FIRECRAWL_API_KEY` | Codex, Claude, and generic MCP; Agent Equipment also declares Cursor |
| `github` | `GITHUB_PERSONAL_ACCESS_TOKEN` | Codex and Claude; Agent Equipment declares Claude and Cursor while retiring Codex direct MCP |
| `greptile` | `GREPTILE_API_KEY` | Claude |
| `proton-session` | `PROTON_PASS_PERSONAL_ACCESS_TOKEN` | No public direct consumer; readiness uses the fixed native-store bootstrap identity instead |
| `site-publication` | `SITE_PASSWORD` | No public direct caller in this repository |

The seven sibling templates under
`home/dot_config/private_secret-exec/private_profiles/` render one profile each.
`private_commands.env.tmpl` renders the command map. The value-free catalog
projection confirms these current mappings:

```text
k9s=aws
sz=aws
```

Chezmoi's private source names produce a mode-`0700` target directory and
mode-`0600` profile and command-map files. Public sources contain no backend
locators; `tests/fixtures/secret-exec-public.toml` is synthetic shape evidence,
not production mapping evidence.

## Consumer bindings

| Consumer surface | Managed source | Current route |
| --- | --- | --- |
| Codex MCP | `home/dot_codex/modify_private_config.toml.tmpl` | Context7, Firecrawl, and GitHub through the absolute `~/.local/bin/secret-exec` launcher |
| Claude MCP | `home/modify_private_dot_claude.json.tmpl` | Context7, Firecrawl, GitHub, and Greptile through the launcher |
| Claude plugin retirement | `home/dot_claude/modify_private_settings.json.tmpl` | Disables the Context7, GitHub, and Greptile plugin routes that would conflict with the managed MCP routes |
| Generic MCP | `home/dot_config/modify_private_mcp-config.json.tmpl` | Firecrawl through a local stdio launcher, with URL and ambient-auth fields removed |
| OpenCode | `home/run_after_update-opencode-context7.sh.tmpl` | Context7 through a local launcher array; an explicit disabled state is preserved |
| AWS default profile | `home/private_dot_aws/modify_private_config.tmpl` | `secret-exec aws-credential-process aws`; higher-precedence default-profile auth settings are removed while unrelated profiles remain |
| `k9s` and `sz` | `home/private_dot_local/lib/secret-exec/bin/symlink_*` | The dispatcher reads the private map, finds the first later executable with the same name on runtime `PATH`, then invokes the `aws` profile |

`home/private_dot_local/lib/secret-exec/executable_secret-exec-command` owns the
shim algorithm. It rejects missing, malformed, duplicate, unknown, or recursive
mappings. An absolute executable path bypasses command lookup and therefore
bypasses the shim. `home/dot_config/environment.d/99-secret-exec-shims.conf`
places the shim directory first on managed `PATH`; the macOS GUI path bridge
projects the external Zsh startup policy into launchd.

The profile renderers for `proton-session` and `site-publication` have no
public direct caller. They remain installed catalog inputs and affect the global
managed-name scrub. An external or manual caller could also name a profile
directly; no such caller is proven by this repository.

## Agent Equipment contracts

The managed catalog and lock are byte-identical to their proposed documentation
copies at this commit:

- `home/dot_config/agent-equipment/catalog-v1.json`
- `docs/agent-equipment/initial-catalog.proposed.json`
- `home/dot_config/agent-equipment/lock-v1.json`
- `docs/agent-equipment/initial-lock.proposed.json`

They declare nine active `secret-exec -- npx` routes:

- Context7 for Claude, Codex, and Cursor;
- Firecrawl for Claude, Codex, and Cursor;
- GitHub for Claude and Cursor; and
- Greptile for Claude.

The catalog selects the native Codex GitHub plugin and records the direct Codex
GitHub route as a retirement. Current Codex source and legacy-retirement
validation still require that direct wrapped route. This is a concrete desired
state/current-binding conflict for the later disposition and migration-boundary
decisions; it is not current convergence.

No Cursor-specific MCP/`secret-exec` consumer overlay is tracked under `home/`.
The catalog's Cursor routes are desired-state references, not evidence of a
current managed secret-injection caller; the generic MCP overlay manages
Firecrawl only.

Catalog and lock schemas allow closed, typed `secret_profile` references.
Discovery and validation require a profile reference to be the first argument
of a `secret-exec` provider and require the declared references to match their
use. The updater preserves exactly one reviewed `secret-exec -- npx` boundary
when changing an npm selector. These rules live in:

- `home/private_dot_local/lib/agent-equipment/agent_equipment/discovery.py`;
- `home/private_dot_local/lib/agent-equipment/agent_equipment/validator.py`;
- `home/private_dot_local/lib/agent-equipment/agent_equipment/updater.py`; and
- `home/private_dot_local/lib/agent-equipment/agent_equipment/plan_action_set.py`.

Agent Equipment is desired-state and planning machinery. It does not itself
resolve a credential or prove an authorized live migration. It also does not
currently model AWS credential-process mode, generic MCP, OpenCode, shims,
profile installation, provider readiness, startup bindings, status, or the
native-store bridge.

## Adjacent lifecycle and migration owners

### Provider readiness

`home/private_dot_local/bin/executable_proton-pass-ensure-ready` owns the lazy,
serialized repair path for pass-backed profiles. It:

- scrubs an inherited bootstrap token before child execution;
- performs a bounded remote `pass-cli info` readiness probe;
- records only enumerated, value-free state and failure classifications;
- serializes repair and supports bounded concurrent waiters;
- classifies only the complete recognized absent or invalidated diagnostic,
  optionally preceded by one or more matching nonempty Proton log records;
- requires every framing record to be either plain or canonically decorated
  with the supported CLI's reset, dim, and red ANSI SGR sequences, rejects mixed
  framing modes and all other controls or record shapes, and keeps the terminal
  diagnostic byte-exact and unstyled;
- treats blank, malformed, transient, timed-out, and unknown diagnostics as
  non-mutating failures that do not read the bootstrap item;
- logs in directly for the absent state and logs out first only for the exact
  invalidated-session state;
- obtains the fixed bootstrap item from the native-store adapter;
- confines the bootstrap value to the login child; and
- verifies readiness before reporting success.

`home/private_dot_local/bin/executable_proton-pass-session` is only a
compatibility alias. `home/private_dot_local/bin/executable_proton-pass-startup`
adds two bounded proactive attempts and best-effort notification. Linux systemd
and macOS LaunchAgent targets invoke startup at graphical login; the activation
hook registers or starts them only inside the appropriate session. Linux's
`98-proton-pass.conf` selects the D-Bus keyring provider.

On macOS, startup first resets to the system path baseline, then runs a bounded
fixed-interpreter child that scrubs the bootstrap token and sources the shared
Zsh startup policy as `launcher darwin`. A private unlinked transport accepts
exactly one nonempty `PATH` line. Policy failure, timeout, invalid output, or
surviving descendants fail startup closed before the readiness attempts. This
source contract does not prove the effective Aqua or managed-host environment.

These are lifecycle dependencies of pass-backed launches, not profile
injection. Direct Secret Service profiles do not invoke Proton readiness.

### Native-store bridge

`home/private_dot_local/bin/executable_secret-exec-native-store` has two
operation-specific roles:

- `proton-bootstrap` reads the fixed Linux Secret Service or macOS Keychain
  bootstrap item for readiness; and
- `lookup <profile> <name>` supplies the Linux-only Secret Service backend used
  by the data plane.

The adapter selects fixed system tools and validates them before execution. It
is an incident bridge, not the planned strict native `secretctl` boundary.

### Legacy migration and retirement

`home/private_dot_local/bin/executable_secret-exec-migrate` is operator tooling,
not a consumer runtime dependency. Its installed entrypoint uses fixed
`/bin/zsh -f`. It invokes `pass-cli` by command name through runtime `PATH`, but
requires Python, jq, and retirement-only grep, awk, rm, and Codex selections to
resolve to absolute runtime paths before using them to encode, inspect, or
remove plaintext. Its default mode:

- accepts either all three known legacy plaintext sources or none;
- requires duplicate legacy sources to agree;
- creates missing Proton Pass objects without overwriting a different existing
  value; and
- verifies the installed references idempotently.

Only explicit `--retire-plaintext` enters retirement. Before deletion it checks
the launcher and dispatcher shape, a nonempty syntactically valid private
profile set, a nonempty syntactically valid command map with corresponding
shims, active shim `PATH`, the provider selector, the hardened Zsh loader, and
the exact current Codex, Claude, generic MCP, optional OpenCode, and AWS
overlays. It rejects a fixed set of legacy and tool-specific ambient credential
names, stale credential files, source-value remnants when legacy sources are
present, and consumer drift. That ambient scan is not derived from the complete
installed catalog: the `proton-session` and `site-publication` managed names are
outside it. It also does not compare the deployed private state with the source
catalog's exact seven profiles and `k9s`/`sz` mappings, or compare the launcher
with reviewed bytes. Any failure before deletion preserves the legacy sources.

The current importer is not transactional. Provider objects created before a
later failure are not compensated, and the final multi-file deletion can
partially succeed. Agent Equipment documents a stronger digest-bound,
compare-before-mutate compensation model, but that model is not the current
migration controller.

## Documentation surface

| Document | Owned contract and inventory disposition |
| --- | --- |
| `docs/secret-injection/CONTEXT.md` | Defines the data-plane, control-plane, lifecycle, adapter, and trust boundaries used by this inventory. |
| `docs/SECRET_INJECTION.md` | Describes the current operator workflow, profile and shim contracts, provider readiness, migration, and rollback. Its statement that a cleanup failure preserves every plaintext source is stronger than the current multi-file deletion behavior and must be reconciled before it can serve as replacement acceptance evidence. |
| `docs/ENCRYPTION.md` | Owns the encrypted-source format, public manifest inventory, structural scanner, trusted-base verifier, and owner-signed admission boundary. |
| `docs/agent-equipment/CONTEXT.md`, `ARCHITECTURE.md`, and `INVENTORY.md` | Define the broader desired-state model and classify the current wrapped consumer routes; they do not prove live migration. |
| `docs/agent-equipment/MIGRATION.md` | Defines the future digest-bound plan, compensation, rollback, and evidence model; it does not authorize a host mutation. |
| `docs/agent-equipment/ACCEPTANCE.md` and `IMPLEMENTATION_HANDOFF.md` | Allocate future security, platform, host, and execution gates that a replacement must satisfy. |

## Verification surface

| Suite or artifact | Contract it owns |
| --- | --- |
| `tests/secret-exec.zsh` | Clean interpreter, private profile grammar, global scrub, selected-only resolution, ordinary runtime-`PATH` and symlink selection, bounded provider processes, descriptor isolation, signals, descendant cleanup, target exec and exit status, lazy readiness, Secret Service, AWS JSON, and value-free failures |
| `tests/secret-command-shims.zsh` | Private command map, later-executable lookup, recursion avoidance, argument and exit preservation, fail-closed mappings, and trace safety |
| `tests/secret-injection-bindings.zsh` | Codex, Claude, generic MCP, OpenCode, AWS, profile rendering, absence of public locators, and Linux provider selector |
| `tests/proton-pass-session.zsh` | Runtime-`PATH` and symlink selection, remote readiness, complete plain or canonical-ANSI structured diagnostic framing, mixed and malformed framing rejection, fail-closed unknowns, serialized repair, lock and adapter trust, bootstrap scrubbing, bounded descendants, status, and value-free diagnostics |
| `tests/proton-pass-startup.zsh` | Finite retry, bounded macOS GUI-`PATH` derivation, deadline, signal and descendant cleanup, backoff, notification, and bootstrap scrubbing |
| `tests/proton-pass-startup-bindings.zsh` | Linux systemd transaction and macOS LaunchAgent/activation shape |
| `tests/secret-exec-migrate.zsh` | Fixed interpreter, runtime `pass-cli`, absolute plaintext-tool selection, idempotent import, drift rejection, explicit retirement, exact consumer gates, the fixed ambient-name scan, literal-source checks, and preservation on validation failure |
| `tests/test_chezmoi_source_ownership.py` | Private `~/.config/secret-exec` directory deployment |
| `tests/zsh-gui-path.zsh` | Shim and launcher path projection into the macOS GUI session |
| `tests/platform-portability.zsh` | Frozen platform-specific source inventories |
| `.github/workflows/platform-portability.yml` | Runs the secret-exec, readiness, binding, migration, Agent Equipment, and privacy suites natively on macOS 14 and Ubuntu 24.04 |
| `.github/workflows/zsh-deployment-portability.yml` | Runs the GUI-path and startup-binding deployment suites on both macOS and Ubuntu and requires both jobs before aggregate success |
| `.github/workflows/privacy-age-integrity.yml` | Verifies trusted-base and candidate bytes, the public envelope inventory, structural policy, and owner-signed protected-change admission without trusting candidate code |
| `tests/test_privacy_age_envelopes.py`, `tests/test_privacy_age_integrity_gate.py`, and `tests/test_privacy_age_admission.py` | Exercise the envelope manifest and parser policy, trusted-base integrity gate, admission receipt, and fail-closed protected-transition boundary |
| Agent Equipment schema/design/deployment tests | Closed secret references, exact wrapped npm boundary, catalog/lock agreement, and safe update planning |
| `tests/privacy-scan.zsh` and `scripts/privacy-scan` | Public-source secret patterns, output redaction, and age-envelope manifest integrity |

The behavioral suites in the two portability workflows establish synthetic and
source-level behavior on macOS 14 and Ubuntu 24.04. The privacy workflow
separately enforces the trusted admission boundary. These checks use
deterministic synthetic values and fake providers, so they do not prove live
Proton Pass or native-store behavior on a managed host, the actual login-session
GUI `PATH`, or deployment and rollback convergence.

Rendered-mode coverage verifies the private directory as mode `0700`, while
runtime tests reject unsafe profile and command files. The deployment test does
not independently stat every rendered file as mode `0600`.

## Reviewed guarantees

| Reviewed change | Guarantee inherited by this inventory |
| --- | --- |
| [Scope credentials to consumer processes](https://github.com/nisavid/dotfiles/pull/13), reviewed [`24b92e9`](https://github.com/nisavid/dotfiles/commit/24b92e98ad723e00a3bfaceb69f1d7fd675c83fb) | Scrub every managed name, resolve only the selected profile, preserve direct child argv/I/O/TTY/exit behavior, keep ordinary shells credential-free, retain the narrow AWS adapter, and gate plaintext retirement on every binding. |
| [Inject profiles through command shims](https://github.com/nisavid/dotfiles/pull/19), reviewed [`e32cc36`](https://github.com/nisavid/dotfiles/commit/e32cc3698a11666e73c2bb93be0ebbaa5bc394d3) | Route `k9s` and `sz` through explicit fail-closed shims, find the first later executable, and let absolute paths bypass interception intentionally. |
| [Chart the agent-backed injection system](https://github.com/nisavid/dotfiles/pull/40), reviewed [`d513d92`](https://github.com/nisavid/dotfiles/commit/d513d92e89762d68180b31e4bb8140ce476c2485) | Keep the minimal data plane separate from the control plane; declare shims and application bindings; reject launch on provider failure; keep bootstrap in the session layer; use durable status and best-effort notification. |
| [Reconcile private state and PR tooling](https://github.com/nisavid/dotfiles/pull/41), reviewed [`0476290`](https://github.com/nisavid/dotfiles/commit/04762901b794ff32967c1763349bba90f0abb518) | Preserve the mode-`0700` secret-exec state directory. |
| [Recover provider sessions automatically](https://github.com/nisavid/dotfiles/pull/99), reviewed [`1a890e5`](https://github.com/nisavid/dotfiles/commit/1a890e556ed8d5e3b5dff709b923e8cb5a27b089) | Pass-backed launches depend on fail-closed lazy readiness; native-store-only profiles do not. Repair is serialized, bounded, descendant-cleaning, and value-free; enrollment and rotation remain operator actions. |
| [Reconcile agent policy and Proton Pass readiness](https://github.com/nisavid/dotfiles/pull/102), reviewed [`94d766f`](https://github.com/nisavid/dotfiles/commit/94d766f577327d189c6da53c0fcc6d4fa64fda05) | Classify readiness failures before mutation; preserve a potentially usable session on unknown/transient failure; permit logout only for the exact invalidated-session case; remove private diagnostics before teardown. |
| [Add owner-signed protected transition admission](https://github.com/nisavid/dotfiles/pull/130), reviewed [`ce9f5c9`](https://github.com/nisavid/dotfiles/commit/ce9f5c9cbbc5c21318b45f2a237cbf60fb4b4897) | Treat the public age manifest as an integrity inventory, not authentication; require the trusted-base verifier and an owner-signed admission receipt for protected envelope changes. |
| [Restore provider session recovery](https://github.com/nisavid/dotfiles/pull/188), reviewed [`3231246`](https://github.com/nisavid/dotfiles/commit/323124667087a6f124ad5cb1090b3b30dccf00ad), integrated as [`c0eb321`](https://github.com/nisavid/dotfiles/commit/c0eb321a6464be62ad7fc8650c448767557d07c0) | Invoke `pass-cli` by command name through runtime `PATH` across the data plane, readiness, and migration; repair only complete recognized absent or invalidated diagnostics with bounded structured framing; derive macOS startup `PATH` in a bounded process; and keep plaintext-handling migration tools on selected absolute paths. |
| [Accept canonical ANSI diagnostics](https://github.com/nisavid/dotfiles/pull/192), reviewed [`c158568`](https://github.com/nisavid/dotfiles/commit/c158568a8f18ed81c0e873c87f476065c307b13f), integrated as [`bff0415`](https://github.com/nisavid/dotfiles/commit/bff0415c7d05e08c8f918cebb8860e9997fee2b1) | Accept the supported CLI's complete canonical ANSI log framing without broadening recovery: require a single mode across any framing records, exact SGR placement, an unstyled terminal diagnostic, and fail-closed rejection of malformed or mixed records. |

The fixed `pass-cli` candidates introduced by the earlier readiness bridge are
historical implementation, not a retained requirement. PR #188 replaced them,
so normal runtime-`PATH` selection is both current source behavior and the map's
settled replacement rule. Package-version pinning for audited credentialed
consumer packages remains a separate reviewed guarantee. PRs #188 and #192
were source-and-fixture work; they did not prove deployment, the selected
executable, or recovery on either managed host.

## Adjacent tickets and rollback boundary

The related secret-injection, recovery, and Agent Equipment tickets remain
separate. This inventory does not disposition them:

- [Repair PAT-backed Proton Pass session recovery](https://github.com/nisavid/dotfiles/issues/186)
  is complete in the reviewed source delivered through PRs #188 and #192. Its
  closure proves source and fixture behavior, not live-host deployment,
  executable selection, or recovery.
- [Roll out and verify Proton Pass recovery on both hosts](https://github.com/nisavid/dotfiles/issues/187)
  owns actual runtime-`PATH` selection, value-free recovery checks, deployment
  convergence, and bounded rollback on the two managed hosts. None occurred in
  this inventory.
- [Agent equipment Step 7: implement MCP adapters and the secret
  boundary](https://github.com/nisavid/dotfiles/issues/75) still owns adapter
  value confinement, reference-only durable artifacts, explicit route conflict
  selection, and preservation of unrelated configuration.
- [Agent equipment Step 8b](https://github.com/nisavid/dotfiles/issues/80)
  still owns digest-bound release, rollback, and disposable evidence without
  live-host migration authority.
- [Classify the current system](https://github.com/nisavid/dotfiles/issues/87)
  still needs retain, absorb, replace, remove, or split dispositions.
- [Prototype secretctl workflows](https://github.com/nisavid/dotfiles/issues/88),
  [Define reconciliation and recovery](https://github.com/nisavid/dotfiles/issues/90),
  [Define startup readiness](https://github.com/nisavid/dotfiles/issues/91),
  [Define host enrollment and rotation](https://github.com/nisavid/dotfiles/issues/92),
  and [Define the injection catalog](https://github.com/nisavid/dotfiles/issues/93)
  remain control-plane, lifecycle, or catalog decisions.
- [Choose the implementation substrate](https://github.com/nisavid/dotfiles/issues/89)
  remains a mixed data-plane/control-plane decision.
- [Review the security architecture](https://github.com/nisavid/dotfiles/issues/94),
  [Specify the acceptance matrix](https://github.com/nisavid/dotfiles/issues/95),
  and [Produce the implementation handoff](https://github.com/nisavid/dotfiles/issues/96)
  remain later gates.

Any replacement or rollback plan must account for all of these obligations:

1. preserve complete managed-name scrubbing and selected-profile-only
   resolution;
2. preserve direct consumer stdin, stdout, stderr, TTY, signal, argv, and exit
   behavior, or record and accept each deviation explicitly;
3. preserve the special AWS `credential_process` contract;
4. migrate every application overlay, including Claude's separate MCP and
   plugin-retirement overlays, optional OpenCode binding, command shim, private
   profile and command target, Agent Equipment catalog/lock route, schema,
   validator, updater, test, and operator document;
5. retain provider readiness, bootstrap, startup, status, and native-store
   responsibilities until a reviewed replacement owns each one;
6. resolve the direct Codex GitHub/catalog retirement conflict explicitly;
7. verify runtime `PATH` selection independently in each process context;
8. preserve unrelated configuration and the absence of ambient credentials;
9. keep a bounded rollback to the reviewed launcher and bindings until both
   managed hosts converge; and
10. remove legacy or current files only after no caller, generated contract,
    managed target, startup hook, test, or documentation reference remains.

The [crypto-operations map](https://github.com/nisavid/dotfiles/issues/133) and
key-material custody remain separate. As assumption checks only,
[host CLI/provider qualification](https://github.com/nisavid/dotfiles/issues/150)
shares the runtime-`PATH` and readiness boundary, while the
[custody contract](https://github.com/nisavid/dotfiles/issues/139) and
[offline-recovery fixture](https://github.com/nisavid/dotfiles/issues/158)
retain all key-material responsibilities. This inventory transfers no ownership
to or from those tickets and does not use `pass-cli run` for key material.
