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

Proton Pass sessions are local to each host and can become unauthenticated
while local session files remain. A successful remote `pass-cli info` call,
with its output suppressed, is the readiness signal. Local files, a running
Secret Service, and notification delivery are not readiness signals.

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
  cannot tell the two apart. It accepts that trade-off: two independent
  readiness checks must both report the chain, and the worst outcome replaces
  a still-valid local session with a fresh one.
- An invalidated session is the automatic-logout report of older `pass-cli`
  releases.

Orphaned and invalidated sessions both require a successful
`pass-cli logout --force` before login. Forced logout is local only: it removes
the provider's local session directory, its session-scoped keyring key, and any
legacy shared `cli-local-key` keyring entry, and it never contacts the
provider. Readiness checks that other callers make before taking the lock, and
consumers already resolving values, are not serialized with that cleanup and
the following login. In that brief window one of them can observe the removed
session or recreate a local key and make this repair fail closed. The helper
gives the bootstrap value only to a background subshell that immediately
replaces itself with the trusted `pass-cli login` backend. The
controller clears its non-exported copy immediately after the fork, the caller
clears its shell value after registering the process group, and readiness
verifies the repaired session before returning.
The lock uses zsh's `zsystem flock`, so the repair path has no external `flock`
dependency. The helper rejects symbolic-link, non-regular, wrong-owner, or
replaced lock files and compares the locked descriptor with the published
device and inode before using it. Lock acquisition allows a six-second
takeover window, plus up to twenty more seconds while a valid repair is in
progress.
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
descriptors; the controller receives only an exit-status marker. The lock
grants a six-second takeover window when no repair succeeds; it outlasts a
timed-out classifying check, so a caller that began waiting as that check
started can still take over. A caller that finds a valid repair still in
progress can wait another twenty seconds, then rechecks readiness without
starting a second repair. Every path remains below the 36-second per-call
startup budget, including cleanup and bounded polling overhead: a takeover
followed by forced cleanup and login and the extended concurrent wait each
need at most 34.6 seconds.
`secret-exec` and its shims call the helper without an outer deadline, so a
lazy consumer can wait up to that bound before its first value resolves. The
helper logs out only when the provider reports the complete recognized
invalidated-session diagnostic or the byte-exact orphaned-session diagnostic.
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
failed token refresh, remain unclassified. The forced local cleanup must
succeed before login.

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
2.15-second notification ceiling total 82.30 seconds. Process-group creation
and other fixed local handling use the remaining 7.70-second margin under the
Linux service's 90-second startup ceiling. The PATH phase runs only on macOS,
so the Linux worst case is 79.15 seconds; because the service runs before
desktop autostart, double exhaustion delays autostart by up to that long. The
Linux activation hook starts the oneshot service synchronously, so the same
double exhaustion can hold `chezmoi apply` for up to that long.
Exhaustion records the underlying value-free failure when available, emits a
best-effort notification, and leaves lazy consumer recovery enabled.

### Status and locked stores

Readiness publishes an atomic mode-`0600` status file beneath
`$XDG_STATE_HOME/secret-exec`, defaulting to
`~/.local/state/secret-exec/proton-pass-readiness.status`. It contains only
`state`, an enumerated `reason`, an enumerated `waiter-stage`, and an update
timestamp. `state` is `ready` or `unavailable`. A ready `reason` is
`existing-session`, `concurrent-repair`, or `repaired`. An unavailable
`reason` is one of:

- `unsafe-lock`, `lock-timeout`, or `concurrent-repair-failed`;
- `session-probe-timeout` or `session-state-unknown`;
- `native-store-timeout`, `native-store-unavailable`, or
  `invalid-bootstrap-value`;
- `logout-timeout` or `logout-failed`;
- `login-timeout`, `login-failed`, `login-already-authenticated`,
  `login-token-rejected`, `login-token-malformed`, or `login-session-refused`;
- `verify-timeout` or `verify-failed`.

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
to an individual concurrent consumer attempt. A later attempt therefore
replaces an earlier, more specific failure: preserving it would require trusting
and correlating a previous status file. The file never contains provider
output, account metadata, locators, or credential values.

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
profile.

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
