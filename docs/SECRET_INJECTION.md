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

When repair is needed, the helper serializes callers and classifies a second
bounded readiness check from a private diagnostic file. A positively identified
unauthenticated state proceeds directly to login. A positively identified
invalidated session first requires a successful `pass-cli logout --force`;
unknown or transient failures preserve the local session and fail closed. The
helper then retrieves the fixed bootstrap item from the native credential store
and gives the value only to a background subshell that immediately replaces
itself with the trusted `pass-cli login` backend. The controller clears its
non-exported copy immediately after the fork, the caller clears its shell value
after registering the process group, and readiness verifies the repaired
session before returning.
The lock uses zsh's `zsystem flock`, so the repair path has no external `flock`
dependency. The helper rejects symbolic-link, non-regular, wrong-owner, or
replaced lock files and compares the locked descriptor with the published
device and inode before using it. Lock acquisition waits at most five seconds.
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
before the consumer starts. A remote info check, stale-session cleanup,
native-store read, and verification each have a three-second deadline; login
has an eight-second deadline. Each bounded operation and all of its descendants
run in a dedicated process group. Timeout cleanup sends `TERM`, then `KILL`
within a 100-millisecond cleanup window and reaps the managed child. Provider
output bypasses the process-group controller through inherited anonymous descriptors;
the controller receives only an exit-status marker. The lock grants a
five-second takeover window when no repair succeeds. A caller that finds a valid
repair still in progress can wait another thirteen seconds, then rechecks
readiness without starting a second repair. The takeover path and the extended
concurrent-wait path each remain below the 26-second per-call startup budget,
including cleanup and bounded polling overhead. The helper logs out only when
the provider reports the complete recognized invalidated-session diagnostic.
The corresponding `pass-cli` main-command error record may frame a complete
recognized absent or invalidated diagnostic. Other structured logs, arbitrary
prefixes or suffixes, and diagnostic fragments remain unclassified. The forced
local cleanup must succeed before login.
Platform selection uses zsh's `OSTYPE`, so no external platform probe runs
ahead of the first bounded info call. Unknown provider failures never read the
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
with a three-second deadline; failure, extra output, or surviving descendants
fail startup closed.

Both startup targets call `proton-pass-startup`, which uses a fixed finite
two-attempt schedule with a five-second backoff around the shared readiness
helper. On macOS, the bounded PATH-policy setup adds at most 3.1 seconds. Two
26-second attempts, the backoff, the PATH-policy ceiling, and a 2.15-second
notification ceiling total 62.25 seconds, leaving 7.75 seconds for remaining
local setup and fixed error handling under the Linux service's 70-second startup
ceiling. Exhaustion records the underlying value-free failure when available,
emits a best-effort notification, and leaves lazy consumer recovery enabled.

### Status and locked stores

Readiness publishes an atomic mode-`0600` status file beneath
`$XDG_STATE_HOME/secret-exec`, defaulting to
`~/.local/state/secret-exec/proton-pass-readiness.status`. It contains only
`state`, an enumerated `reason`, an enumerated `waiter-stage`, and an update
timestamp. `waiter-stage` is `record`, `identity`, `liveness-retry`,
`child-status`, `retirement`, or `unrecorded`; `child-status` means the bounded
controller reported a nonzero status and does not imply a natural provider
exit. The atomic `reason`/`waiter-stage` tuple is last-writer-wins shared
readiness state; it identifies the latest recorded outcome and is not correlated
to an individual concurrent consumer attempt. The file never contains provider
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
idempotent.

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
