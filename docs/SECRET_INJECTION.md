# Process-scoped secret injection

`secret-exec <profile> -- <command> [args...]` resolves one managed profile,
removes every managed credential name inherited from the parent, exports only
the selected values, and replaces itself with the target command.

Ordinary login, interactive, and non-interactive shells do not receive managed
credentials. Consumer configuration contains launcher arguments rather than
literal values, credential-bearing URLs, or ambient environment bindings.

## Profile contract

Chezmoi keeps the profile catalog encrypted. Apply renders individual profile
files into a mode-`0700` directory with mode-`0600` files. Profile names and
credential names must be unique and syntactically valid.

Each assignment uses one of these locators:

- `pass://...` resolves a single field through the Proton Pass CLI.
- `secret-service://` resolves an exact attribute tuple through Secret Service
  on Linux. General profile lookup is not supported on macOS; Keychain is used
  only for the fixed Proton bootstrap item.
- `!ENV` removes an inherited variable without resolving a replacement.

The launcher rejects malformed profiles, loose permissions, unsupported
locators, missing values, duplicate names, and multiline values before starting
the consumer. It disables shell tracing before secret resolution and never
places resolved values in command arguments. Each Proton Pass item read and
Secret Service lookup has a three-second deadline. The provider and all of its
descendants run in a dedicated process group; timeout cleanup sends `TERM`,
then `KILL`, and reaps the managed child before the launcher returns. Resolved
values travel only through inherited anonymous descriptors and shell memory.

The launcher also exports `SECRET_EXEC_INJECTED_PROFILES`, a non-secret
provenance marker that names the profile whose values the target received. The
launcher drops any inherited marker before it resolves anything, so readiness
checks, providers, and failed launches never see a stale one. Because the scrub
removes every other profile's credentials, a nested launch replaces the marker
rather than appending to it: after `secret-exec A -- secret-exec B -- cmd`, the
marker names only `B`. The marker never carries a value. Profiles must not map
or unset it or any other `SECRET_EXEC_*` name, which the launcher reserves for
its own state.

When the inherited marker names the selected profile as a whole
space-separated word and every value that profile maps is present, non-empty,
and a single line, the launcher reuses those values. It skips readiness and
resolution, still removes every other managed name, including names the profile
unsets with `!`, and then execs the target with the marker set to that profile.
A marker that merely contains the name, such as `typesafe-extra` for
`typesafe`, does not match. If any value is missing, the launcher resolves the
profile normally. `aws-credential-process` always resolves.

The marker is not authenticated, and reuse trusts the inherited value. A
process that sets the marker next to its own value for a mapped name gets that
value passed through in place of the managed one, exactly as if it had run the
target directly. A spoofed marker cannot make the launcher fetch, reveal, or
widen access to any value: it only suppresses a lookup whose result would have
replaced the caller's own value.

Proton Pass sessions are local to each host and can become unauthenticated
while local session files remain. A successful remote `pass-cli info` call,
with its output suppressed, is the readiness signal. Local files, a running
Secret Service, and notification delivery are not readiness signals.

### Best-effort launches

`secret-exec --best-effort <profile> -- <command> [args...]` injects exactly
like an ordinary launch while the provider is available. If it is not, the
launcher starts the target without the profile's credentials instead of
failing. Profile names cannot start with `-`, so the option cannot be mistaken
for a profile. Shims reach it through `name=profile?` mappings (see
[Command shims](#command-shims)); agent-equipment MCP routes still require the
profile as the launcher's first argument and do not accept the option.

Best-effort covers provider availability, not the launch contract. These
failures stop the launch in both modes:

- usage errors: a missing `--` or target, or `--best-effort` combined with
  `aws-credential-process`
- profile-catalog errors: directory or file permissions, symbolic links,
  malformed or duplicate mappings, unsupported locators, an unknown or empty
  profile, or a profile that manages a reserved `SECRET_EXEC_*` name
- a failure to remove an inherited credential name

The fallback boundary is the scrub. Once the catalog has loaded and every
managed name is gone, a later resolution failure falls back. That includes a
missing or failing readiness helper (a locked native store, for example), a
missing or untrusted provider command, a provider timeout or failure, including
one whose process group became unmanageable, and a resolved value that is empty
or spans lines. Two post-scrub failures still stop the launch: signals, and a
failure to close the launcher's diagnostic channel after every value resolved.

On fallback, the launcher unsets every value it had already exported and the
provider request variables, and it does not export the provenance marker.
Standard error keeps the usual value-free diagnostic and gains one `starting
<command> without <profile> credentials` line. The launcher sends one desktop
notification and then execs the target, so the target's own exit status is the
launch status.

The notification's title is `Credentials unavailable`. Its body names only the
profile and the command's base name, or `A command` when that name contains
unusual characters. It never includes a value, locator, or provider output,
and it does not guess at a cause: it asks only for a restart once the
credential provider is available. Stderr keeps the value-free reason, and so
does the readiness status when the readiness helper records the failure. Linux sends it with `notify-send`; macOS passes the text to
`osascript` as arguments, not as script source. Either command is found on
`PATH`, like `pass-cli`, and a missing notifier skips the notification. It runs
detached with its output discarded and is killed after two seconds, so it
neither delays the target nor outlives its bound.

## Provider readiness and recovery

`proton-pass-ensure-ready` owns one idempotent repair path. It disables tracing,
removes any inherited Proton personal access token before starting a child,
validates the remote session, and returns without reading the bootstrap item
when the session is ready. `secret-exec` and the `proton-pass-session`
compatibility entrypoint apply the same unconditional bootstrap-token scrub;
the result does not depend on the encrypted profile catalog being complete.
Those entrypoints and the native-store adapter use the fixed `/bin/zsh -f`
interpreter, so neither `PATH` nor zsh startup files can run code ahead of that
scrub.

`proton-pass-ensure-ready`, `secret-exec`, and `secret-exec-migrate` invoke
`pass-cli` as an ordinary command through their runtime `PATH`. They do not
encode package-manager preferences, fixed candidate paths, executable-path
overrides, or a separate symbolic-link policy; package-managed entrypoints such
as Homebrew's normal `bin/pass-cli` symlink therefore work when that entrypoint
is selected by `PATH`.
Native-store access does not use `PATH` and crosses the verified fixed sibling
`~/.local/bin/secret-exec-native-store`; it alone selects
`/usr/bin/secret-tool` on Linux or `/usr/bin/security` on macOS. The parent
validates the adapter before every use, and the adapter applies the same checks
to the system command. Each native-store executable must be regular,
non-symlinked, executable, owned by root or the current user, and not writable
by its group or other users. Readiness status housekeeping also uses fixed
system utility paths instead of ambient `PATH` resolution.

When readiness fails, `secret-exec` preserves the readiness helper's fixed,
value-free diagnostic. It does not replace an unknown, timeout, lock,
stale-session cleanup, login, verification, or native-store failure with
inferred unlock guidance.

When repair is needed, the helper serializes callers and classifies a second
bounded readiness check from a private diagnostic file. Unknown or transient
failures preserve the local session and fail closed. For a positively
classified state, the helper retrieves the fixed bootstrap item from the native
credential store and validates it before changing anything:

- An unauthenticated state, with no stored local authentication, proceeds
  directly to login.
- An orphaned session is one the provider no longer recognizes while
  `pass-cli` still stores local authentication. The provider reports it with
  the byte-exact non-existent-session error chain, and `pass-cli` refuses login
  locally while that authentication remains. The same chain appears when a
  concurrent `pass-cli` process wins a token-refresh race, and the helper
  cannot tell the two apart. It accepts that trade-off: the first readiness
  check must fail and the exclusive classifying check must then report the
  exact chain. The worst outcome replaces a still-valid local session with a
  fresh one; if that login then fails, the call fails with no local session and
  the next call repairs.
- An invalidated session is the automatic-logout report of older `pass-cli`
  releases.
- An undecryptable local store is one the stored local key cannot open:
  `pass-cli` reports the byte-exact database error chain that ends by
  recommending `pass-cli logout --force`. Even an unauthenticated `pass-cli
  info` creates the local database under the local key it resolves, so two
  processes that each create a key for an empty session can leave the database
  under one key and the keyring holding the other. The local data is
  unreadable either way, and login rebuilds it.
- An interrupted repair is one whose login marker (below) survives. The
  session it left may pass `pass-cli info`, so the helper treats a positively
  ready, absent, orphaned, invalidated, or undecryptable state the same way
  behind a marker: it resets the local state and logs in again.

Orphaned, invalidated, and undecryptable states, and every state behind an
interrupted repair, require a successful `pass-cli logout --force` before login.
Forced logout is local only: it removes the provider's local session directory,
its session-scoped keyring key, and any legacy shared `cli-local-key` keyring
entry, and it never contacts the provider. A repair holds the readiness lock
exclusively from before it records its login marker until it has published its
status, and the helper's first readiness check runs under a shared hold on the
same lock. That check therefore waits out a repair, including its cleanup and
login, instead of racing it, while concurrent checks still run side by side.
`secret-exec` value reads stay unlocked until
[#314](https://github.com/nisavid/dotfiles/issues/314) lands: consumers already
resolving values are not serialized with the cleanup and the following login.
In that brief window one of them can observe the removed session or recreate a
local key and make this repair fail closed, or leave an undecryptable store
that the next call resets. The helper
gives the bootstrap value only to a background subshell that immediately
replaces itself with the trusted `pass-cli login` backend. The
controller clears its non-exported copy immediately after the fork, the caller
clears its shell value after registering the process group, and readiness
verifies the repaired session before returning.
The lock uses zsh's `zsystem flock`, so the repair path has no external `flock`
dependency. The helper rejects symbolic-link, non-regular, wrong-owner, or
replaced lock files and compares the locked descriptor with the published
device and inode before using it, for shared and exclusive holds alike. The
first check waits up to one second for its shared hold. If a repair still holds
the lock, the caller skips that check and takes the exclusive path, whose
acquisition allows a six-second takeover window, plus up to twenty more seconds
while a valid repair is in progress. A caller always releases its shared hold
before it waits for the exclusive one, so it never upgrades a lock.
The bootstrap item identity is:

- Linux Secret Service: `application=secret-exec`,
  `profile=proton-session`, and
  `name=PROTON_PASS_PERSONAL_ACCESS_TOKEN`.
- macOS Keychain: service `secret-exec` and account `proton-session`.

Every selected `pass://` profile invokes this operation before resolving its
first value. The first consumer after later session loss therefore performs the
same serialized repair. Direct Secret Service profiles do not invoke Proton
Pass readiness.

`proton-pass-session` remains as a compatibility name and delegates to
`proton-pass-ensure-ready`. New operations can invoke the readiness helper
directly:

```text
proton-pass-ensure-ready
```

The helper accepts no arguments and does not accept an ambient token as a
bootstrap source. An unclassified readiness failure, failed stale-session
cleanup, failed native-store lookup, failed login, or failed verification stops
before the consumer starts. The first remote info check, forced stale-session
cleanup, and native-store read each have a three-second deadline; the
classifying info check and post-login verification each have five seconds;
login has eight. Each bounded operation and all of its descendants run in a
dedicated process group. Timeout cleanup sends `TERM`, then `KILL` within a
100-millisecond cleanup window and reaps the managed child. Provider output
bypasses the process-group controller through inherited anonymous
descriptors; the controller receives only an exit-status marker. The first
check waits up to one second for its shared hold. The exclusive lock grants a
six-second takeover window when no repair succeeds; it outlasts a timed-out
classifying check, and a shared holder runs only the shorter first check, so a
caller that began waiting as either started can still take over. A caller that
finds a valid repair still in progress can wait another twenty seconds, then
rechecks readiness without starting a second repair. Every path remains below
the 36-second per-call startup budget, including cleanup and bounded polling
overhead: after a full shared wait and a timed-out first check, a takeover
followed by forced cleanup and login and the extended concurrent wait each
need at most 35.6 seconds.
`secret-exec` and its shims call the helper without an outer deadline, so a
lazy consumer can wait up to that bound before its first value resolves.
Before login, the helper logs out only when the provider reports the complete
recognized invalidated-session diagnostic, the byte-exact orphaned-session
diagnostic, or the byte-exact undecryptable-store diagnostic, or when a login
marker survives. After a failed login, it logs out as described below.
The readiness and secret-resolution controllers disable Zsh background-job
priority adjustment before creating their PTY sessions, so a denied
`setpriority` operation cannot enter the private status channel.
The complete recognized absent diagnostic may be immediately preceded by the
exact unstyled `Command is not logout there is no session` record. One or more
non-empty corresponding `pass-cli` main-command error records may otherwise
frame a complete recognized absent or invalidated diagnostic. Every such
framing record must be either plain or use the canonical reset, dim, and red
SGR decoration emitted by the supported CLI around its timestamp, severity,
source path, separator, and colon-terminated line number. A diagnostic cannot
mix the two forms. The recognized terminal diagnostic remains byte-exact and
unstyled.
Empty framing, blank records, other controls or structured logs, arbitrary
prefixes or suffixes, and diagnostic fragments remain unclassified. The
orphaned-session diagnostic accepts no framing record, styling, or trailing
line; other forms of the same error, such as the user-account variant or a
failed token refresh, remain unclassified. The undecryptable-store diagnostic
may be preceded only by the local database engine's plain records, each of the
form `YYYY-MM-DD HH:MM:SS.mmm: ERROR CORE <text>` with no control characters;
styled, blank, or `pass-cli` main-command framing, a trailing line, or a
truncated chain remain unclassified. The forced local cleanup must succeed
before login.

A login that fails or times out can leave local authentication behind:
`pass-cli` stores its session before its private token key, so an interrupted
login passes `pass-cli info` while every item read fails, and later readiness
checks would report that session as ready. When login starts, `pass-cli info`
has already rejected any stored local authentication, so none of it is usable.
After any failed login except `login-already-authenticated`, the helper
therefore runs the same forced local logout and records the login's reason.
If that cleanup fails or times out, the helper records `logout-failed` or
`logout-timeout` instead, because the unusable session may survive. The
cleanup's three-second deadline replaces the five-second verification on that
path, so the per-call budget is unchanged.

The cleanup removes whatever local authentication exists when it runs, and the
helper cannot tell how far a failed login got. After a failed waiter, the
login may have completed; the cleanup then discards a complete session and
leaves its provider-side session behind, and the next call logs in again. A
`pass-cli login` run outside the lock between classification and the end of
login can also lose its session. The provider's exact, prompt refusal keeps
that session, but a refusal that times out or arrives with any other text is
unclassified and triggers the cleanup. The helper accepts both outcomes so it
never reports an unusable session as ready.

A helper killed during login, one stopped by a signal, or one whose login child
became unmanageable cannot run that cleanup. Once the bootstrap value is
validated, and before any forced logout and the login, the helper therefore
records a login marker, `proton-pass-login.pending`, holding only its start
time, as a mode-`0600` file in the private state directory. It removes the
marker once the repaired session verifies, or once the cleanup after a failed
login succeeds. It also removes it after an exact
`login-already-authenticated` refusal, which stored nothing. A failed forced
logout, a failed cleanup, a failed verification, or any exit that skips all of
them leaves the marker in place. Every repair runs under the exclusive
readiness lock, and the lock dies with its holder, so a marker found while
holding the lock, shared or exclusive, belongs to a repair that never finished.

The first readiness check runs only under its shared hold and only while no
marker exists. No repair can record a marker, store a partial session, or
clear its marker while that check runs, so the check never reports a
half-written session ready, even one that a failed repair is about to force
out. A caller that finds a marker skips the check and takes the exclusive
path, which forces a local reset and logs in again, unless its classifying
check times out or stays unclassified, which keeps both the session and the
marker. A caller that waited for another repair fails as
`concurrent-repair-failed` behind a marker, like any waiter, and the next call
repairs. A marker that is not a regular file, such as a symbolic link or a
directory, is never followed or replaced: the exclusive path fails as
`login-marker-failed` before it classifies or changes anything, until the
operator removes it. A marker that outlives a repair that did complete costs one
extra login. So does a forced logout that fails without deleting anything: the
next call resets even a session that was still valid, and if that login fails,
readiness is lost where it would otherwise have held. A `pass-cli login` run
by hand outside the helper leaves no marker, and `pass-cli logout --force`
still clears what such a login leaves.

Login writes its standard error only to a fresh mode-`0600` file in the
private state directory; its standard output, which names the account, is
discarded. The helper opens that file and unlinks it before login starts, so
the captured text is reachable only through the helper's and the provider's
descriptors, and not even an uncatchable kill leaves a named copy. Catchable
signals and unmanageable-child escapes close those descriptors before child
teardown. The classifying readiness check captures its diagnostic the same
way. Only after the bounded controller reports a nonzero provider exit does the
helper read, stopping one byte past 4,096 bytes, and compare the text
byte-exactly with fixed provider texts. A match
selects an enumerated status reason and a fixed message; anything else remains
`login-failed`. Captured text never reaches the status file, logs, or
messages.

Platform selection uses zsh's `OSTYPE`, so no external platform probe runs
ahead of the first bounded info call. Every readiness info check runs with
provider telemetry disabled, and the helper removes inherited Rust backtrace
requests and `PASS_LOG_LEVEL` and `MUON_LOG_LEVEL` overrides, so no scheduled
telemetry request, appended backtrace, or extra log record can change the text
being classified. Unknown provider failures never read the
bootstrap item or mutate local authentication state, preserving a potentially
usable session during a network failure.

### Graphical-session startup

Linux installs `proton-pass-ensure-ready.service` as a oneshot user service
wanted by `plasma-workspace.target`. It runs after the KWallet PAM service and
before desktop autostart. The activation hook reloads user units and starts the
service immediately only when both the Plasma workspace and graphical session
targets are active; otherwise the next Plasma login starts it. The unit does
not unlock KWallet, enable lingering, or use a systemd restart loop.

macOS installs the `io.nisavid.secret-exec-provider-ready` per-user LaunchAgent
for Aqua sessions. It runs once at GUI login and has no `KeepAlive` or periodic
polling. The activation hook registers a missing agent in the current user's
Aqua domain and leaves a healthy registration intact. After scrubbing the
bootstrap token, `proton-pass-startup` resets its path to the system baseline
and sources the shared `~/.config/zsh/startup.zsh` policy with `launcher darwin`.
Provider readiness therefore uses the managed graphical-session `PATH` without
depending on LaunchAgent ordering. PATH derivation runs in its own process group
and discards policy output; its private transport accepts only the renderer's
one non-empty PATH line. Policy failure, an invalid result, or surviving
descendants fail startup closed.

Both startup targets call `proton-pass-startup`, which uses a fixed finite
two-attempt schedule with a five-second backoff around the shared readiness
helper. On macOS, the controlled PATH-policy phase allows three seconds, one
50-millisecond polling interval, and 100 milliseconds of termination grace.
Two 36-second attempts, the backoff, that 3.15-second controlled phase, and a
2.15-second notification ceiling total 82.30 seconds. The PATH phase runs only
on macOS, so that part of the Linux worst case is 79.15 seconds.

The Linux unit passes `--await-prerequisites`. Before its attempts, startup then
waits up to 60 seconds for the Secret Service default collection to report
unlocked and for NetworkManager to report a global connection, polling once a
second. The deadline follows the boot clock in `/proc/uptime`, which only moves
forward, so an NTP step during login cannot stretch the wait; if that clock
cannot be read, startup does not wait. Each probe is a read-only D-Bus property
read through the fixed `/usr/bin/busctl`, bounded at two seconds and captured
the way the macOS PATH phase is. A probe that fails or returns anything else
counts as locked for the wallet; if its private transport cannot be created,
startup stops waiting. For the network, only NetworkManager's own report of a
non-global state holds startup; without NetworkManager the network is not
awaited. The wait never prompts for an unlock, and after it expires the attempts
run regardless. The last one-second sleep can begin just before the deadline and
be followed by one more round of both probes, so the wait can end 65.30 seconds
after it began, and the Linux worst case is 144.45 seconds. Process-group
creation and other fixed local handling use the remaining 15.55-second margin
under the service's 160-second startup ceiling. Because the service runs before
desktop autostart, a wait plus double exhaustion delays autostart by up to that
long. The Linux activation hook starts the oneshot service synchronously, so
the same worst case can hold `chezmoi apply` for up to that long. The macOS
LaunchAgent and direct invocations do not wait.

Exhaustion emits a best-effort notification and one fixed-form diagnostic
naming the reason and what to do: unlock the credential store, check the
network, or replace the bootstrap token. Startup reads the readiness status
when it begins and again when it gives up. A value counts as this run's only if
it changed in between, whether its own attempts or a concurrent consumer
changed it, so no clock ordering is involved, and only values in an enumerated
shape are read. Startup names:

1. the status's `last-failure-reason`, if it changed during this run. A
   specific failure is newer evidence than the prerequisite verdict sampled
   before the attempts. The exceptions are the helper's catch-alls,
   `login-failed` and `verify-failed`, which name no cause: `network-offline`
   replaces them, because an offline `pass-cli login` fails with text the
   helper does not recognize. `native-store-locked` does not, because those
   attempts had already read the bootstrap item from the store.
2. otherwise, an unmet prerequisite, `native-store-locked` or
   `network-offline`, which also explains a generic timeout or unclassified
   state better than that state does;
3. otherwise, the status's current reason, if the status changed during this
   run and reports `unavailable`.

Without any of them, the diagnostic names no reason. Startup clears any
inherited copy of its own state before it runs, so only values it computed
reach a message. Lazy consumer recovery stays enabled.

### Status and locked stores

Readiness publishes an atomic mode-`0600` status file beneath
`$XDG_STATE_HOME/secret-exec`, defaulting to
`~/.local/state/secret-exec/proton-pass-readiness.status`. It contains only
`state`, an enumerated `reason`, an enumerated `waiter-stage`, an update
timestamp, and, once a specific failure has occurred, `last-failure-reason` and
`last-failure-at`. `state` is `ready` or `unavailable`. A ready `reason` is
`existing-session`, `concurrent-repair`, or `repaired`. An unavailable
`reason` is one of:

- `unsafe-lock`, `lock-timeout`, or `concurrent-repair-failed`;
- `session-probe-timeout` or `session-state-unknown`;
- `native-store-timeout`, `native-store-unavailable`, or
  `invalid-bootstrap-value`;
- `logout-timeout` or `logout-failed`;
- `login-timeout`, `login-failed`, `login-already-authenticated`,
  `login-token-rejected`, `login-token-malformed`, or `login-session-refused`;
- `verify-timeout` or `verify-failed`;
- `login-marker-failed`, when the login marker cannot be recorded or cleared.

Any other value is recorded as `unrecorded`. The specific `login-*` reasons
come only from the private byte-exact comparison of a reported provider exit.
`login-already-authenticated` means `pass-cli` still stores local
authentication. `login-token-rejected` means the provider rejected the
bootstrap token as invalid, expired, or deleted. `login-token-malformed` means
the bootstrap value is not a well-formed personal access token.
`login-session-refused` means the provider refused to open the preliminary
login session, for example because of rate limiting or a human-verification
challenge. Every other login failure remains `login-failed`.

`waiter-stage` is `record`, `identity`, `liveness-retry`,
`child-status`, `retirement`, or `unrecorded`; `child-status` means the bounded
controller reported a nonzero status and does not imply a natural provider
exit. The atomic `reason`/`waiter-stage` tuple is last-writer-wins shared
readiness state; it identifies the latest recorded outcome and is not correlated
to an individual concurrent consumer attempt.

So that a later generic outcome cannot hide the evidence, `last-failure-reason`
and `last-failure-at` keep the most recent specific failure. They cover
`unsafe-lock`, `native-store-unavailable`, `invalid-bootstrap-value`,
`logout-failed`, every `login-*` failure except `login-timeout`,
`verify-failed`, and `login-marker-failed`. Timeouts, lock waits,
`concurrent-repair-failed`, and `session-state-unknown` never replace them,
and later ready writes keep them. Each write carries them over from the
previous file only when that file is a regular file, the carried reason is one
of those enumerated values, and the carried time is an integer. Anything else
is dropped. Concurrent writers can still race, so the fields record the latest
specific failure one writer saw, not a complete history. The file never
contains provider output, account metadata, locators, or credential values.

If the native store is locked or unavailable, unlock it through the operating
system and retry the consumer. The lazy path will attempt recovery again; no
manual login command is required. Enrollment, bootstrap-item rotation, and
revocation remain explicit operator actions.

### Temporary native-store bridge

The current native-store adapter is an incident bridge. The bounded parent
invokes it only from its verified fixed sibling path. It resolves the fixed
Secret Service item with `/usr/bin/secret-tool` on Linux and the fixed Keychain
item with `/usr/bin/security` on macOS. Output is captured only in the resolving
process, provider diagnostics are suppressed, and the value is never persisted
or placed in arguments.

These command-line adapters are not the final strict native boundary. In
particular, `/usr/bin/security` does not provide the interaction-control and
memory-zeroization contract required of the planned Security.framework
adapter. The future native `secretctl` implementation should absorb the same
fixed item identities, shared state machine, startup bindings, and lazy caller
contract.

## Command shims

The encrypted catalog may also map command names to profiles. Apply renders the
map privately and manages a shim for each command. A shim resolves the first
later executable with the same name, then launches it through the mapped
profile. The shim launches that executable by its `PATH` location without
resolving symbolic links, so a symlinked multi-call binary still receives the
command name it dispatches on.

Every shim goes through the launcher. Inside a process tree that already
carries the mapped profile, the launcher reuses the injected values instead of
repeating the provider lookup (see [Profile contract](#profile-contract)), so a
shimmed command still receives only its profile's credentials.

A mapping ends with `?`, as in `name=profile?`, to make it best-effort. Its
shim launches through `secret-exec --best-effort`, so an unavailable provider
starts the command without that profile's credentials and sends a
notification (see [Best-effort launches](#best-effort-launches)). A mapping
without the suffix keeps failing closed. The suffix follows the profile name
exactly once: `name=profile??`, `name=?`, and `name=?profile` are malformed.
A command may appear only once, with or without the suffix.

The dispatcher rejects missing, duplicate, malformed, and recursive mappings.
An absolute executable path bypasses command lookup and therefore bypasses the
shim. The command map, shim directory, and later `PATH` entries are trusted
user configuration.

## Legacy migration

The migration helper imports supported legacy plaintext sources without
placing values in arguments or temporary files. It verifies that duplicate
sources agree, refuses to overwrite a different existing value, and is
idempotent. Its installed entrypoint uses `/bin/zsh -f`. Commands that directly
encode, inspect, or retire plaintext are selected through runtime `PATH` before
use and must resolve to absolute paths; migration invokes those selected paths
directly.

Run import first:

```text
secret-exec-migrate
```

After applying the encrypted profiles and process-scoped consumer bindings,
retire the old sources:

```text
secret-exec-migrate --retire-plaintext
```

Retirement fails closed unless every required profile, shim, session binding,
and consumer binding matches the canonical contract. It also rejects unexpected
ambient credential exports and known legacy credential files. Failed validation
or cleanup preserves the plaintext sources.

## Claude MCP diagnostics

Claude Code expands `${NAME}` in MCP server arguments from its own environment
before it launches the server. The GitHub and Greptile consumer bindings pass
`mcp-remote` an `Authorization` header built from a `${NAME}` placeholder, and
Claude's environment does not carry those credential names, so Claude keeps the
literal placeholder and lists the name under "Missing environment variables".
`mcp-remote` then substitutes the value from its own environment after
`secret-exec` injects the credential profile. The warning carries only variable
names and confirms that Claude's own environment does not hold the credential.
Do not export the credential into Claude's environment to silence it: Claude
would then place the value in `mcp-remote`'s arguments.

As of Claude Code 2.1.278, Claude also loads `.mcp.json` from the launch
directory and each parent directory as project scope, so an unmanaged
`~/.mcp.json` applies to every project under the home directory. Anthropic's
MCP documentation describes only the project-root `.mcp.json`, so recheck this
behavior after each Claude Code upgrade. Claude reports a same-name server with
a different launch command as a scope conflict. A project server approved
through `enabledMcpjsonServers` or `enableAllProjectMcpServers` also replaces
the managed user-scope consumer binding. In that version,
`claude mcp remove <name> -s project` edits only the current directory's
`.mcp.json`, so run it from the directory that holds the file. Without `-s`,
the command cannot see a parent directory's file and may remove the managed
user-scope entry instead.

## Validation

For each host:

1. Confirm fresh login, interactive, and non-interactive shells do not contain
   managed credential names.
2. Run launcher tests with synthetic values and confirm traced execution does
   not reveal them.
3. Exercise each consumer with a non-destructive authenticated operation.
4. Confirm retired plaintext sources are absent.
5. Confirm managed configuration contains no literal credentials or
   credential-bearing URLs.

Never print, trace, diff, log, or paste a credential value while validating.

## Rotation

Rotate one provider at a time:

1. Create the replacement credential without revoking the old one.
2. Update the backing keyring item through its secure interface.
3. Validate the consumer on every supported host without printing the value.
4. Revoke the old credential.
5. Revalidate the consumer and confirm ordinary shells remain clean.

Rotate multi-field credentials as one unit.
