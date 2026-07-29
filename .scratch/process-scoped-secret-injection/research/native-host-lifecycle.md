# Native host credential and readiness lifecycle

Research date: 2026-07-29. macOS command behavior was checked against the
installed macOS 26.5.2 `security(1)`, `launchd.plist(5)`, `launchctl(1)`, and
`osascript(1)` help/man pages. Linux and Proton behavior uses the current
upstream specifications, manuals, and source.

## Result

The shared architecture can own one state machine and one `ensure-ready`
operation, but it cannot honestly use one native implementation:

- macOS needs a Security.framework adapter, a per-user LaunchAgent, and a
  UserNotifications adapter.
- Linux needs a libsecret/Secret Service adapter, a systemd user service, and a
  freedesktop notification adapter.
- The platform command-line credential tools are suitable for interactive
  enrollment and metadata-only deletion, but not for the strict unattended
  read path: both `security find-generic-password -w` and
  `secret-tool lookup` write the secret to stdout. A compiled helper can keep
  the value in memory, place it only in the child `pass-cli login` environment,
  clear its copy, and never expose it through argv, stdout, logs, or files.
- Native notifications are best-effort GUI-session signals, not readiness
  evidence. Persistent non-secret status and an on-demand `ensure-ready` retry
  remain mandatory.

Startup and lazy recovery should call the same idempotent operation: test the
existing provider session; serialize concurrent repair; if repair is needed,
read the bootstrap token through the platform API, run `pass-cli login` with
only that child receiving `PROTON_PASS_PERSONAL_ACCESS_TOKEN`, remove the
variable immediately after spawn, and verify with `pass-cli test`. Proton
documents the environment variable as its automation input and documents
persisted sessions plus `pass-cli test`
([login reference](https://protonpass.github.io/pass-cli/commands/login/#personal-access-token-login),
[session management](https://protonpass.github.io/pass-cli/commands/login/#session-management)).

## macOS credential store

### Safe interfaces

- Store one generic-password item identified by fixed, non-secret service and
  account attributes. A helper accepts enrollment input on a no-echo TTY,
  holds it as data in memory, and supplies `kSecValueData` to
  [`SecItemAdd`](https://developer.apple.com/documentation/security/secitemadd(_:_:));
  Apple says password item data is encrypted by Keychain Services.
  Replacement uses
  [`SecItemUpdate`](https://developer.apple.com/documentation/security/secitemupdate(_:_:)).
- Read it with an exact
  [`SecItemCopyMatching`](https://developer.apple.com/documentation/security/secitemcopymatching(_:_:))
  query requesting data into the helper's memory. For startup and lazy
  background calls, set the query's authentication-UI policy to fail rather
  than prompt; Apple documents `kSecUseAuthenticationUIFail` among the
  [search attribute values](https://developer.apple.com/documentation/security/search-attribute-keys-and-values).
  The helper must have no command that prints the value; the only permitted
  sink is the environment of the directly spawned login child.
- Delete it by the same exact class/service/account query with
  [`SecItemDelete`](https://developer.apple.com/documentation/security/secitemdelete(_:)).
  Deletion needs no secret input.
- The installed `security add-generic-password` help confirms that putting a
  value in `-w` or legacy `-p` is insecure and that placing `-w` last prompts
  for it. That is an acceptable interactive enrollment fallback. The same help
  says `find-generic-password -w` “Display[s] only the password on stdout,” so
  it is not an acceptable unattended read interface. Shell command
  substitution only captures that stdout; it does not make the interface
  non-output. If the CLI is retained as an enrollment fallback, its trusted-app
  list must explicitly name the installed helper and the helper read must be
  verified immediately; the CLI's default creator trust is not the target
  access policy.

### Access control and non-interactive use

macOS keychain ACLs name trusted applications. Apple defines
[`SecAccessCreate`](https://developer.apple.com/documentation/security/secaccesscreate(_:_:_:))
as taking `SecTrustedApplication` entries allowed to perform restricted
operations without confirmation, and
[`SecTrustedApplicationCreateFromPath`](https://developer.apple.com/documentation/security/sectrustedapplicationcreatefrompath(_:_:))
as the path-based constructor used for item access.

The installed `security` help makes the practical boundary explicit: by
default the application creating an item is trusted; `-T` adds an application;
`-A` trusts every application and is marked insecure. A script has no stable
application identity of its own when it delegates keychain access to
`/usr/bin/security`; trusting that binary is broader than trusting one host
agent. A dedicated, signed compiled helper provides a distinct application
identity that can create and later read its own item. Do not use `-A`, and do
not rely on a prompt being answerable during background startup.

First-party documentation does not fully specify how current code-signing
requirements are preserved across replacement builds for these legacy macOS
ACL APIs. Enrollment acceptance must therefore verify, without displaying the
value, that the installed helper can read the item after an upgrade and after a
reboot; an unexpected access prompt is a failed unattended-read check.
Apple also notes that the login keychain does not unlock automatically when its
password differs from the user login password
([Keychain Access guide](https://support.apple.com/guide/keychain-access/if-you-need-to-update-your-keychain-password-kyca2429/mac)).
That condition is a startup failure, not permission to prompt from a background
job.

## macOS startup and failure visibility

- A user-owned plist in `~/Library/LaunchAgents` is the native standalone
  per-user mechanism. Apple says a per-user launchd context starts when the
  user logs in
  ([Creating Launch Daemons and Agents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html));
  the installed `launchctl(1)` distinguishes `gui/<uid>` from the user domain
  and lists that directory as user-provided LaunchAgents. This is login
  readiness, not pre-login boot readiness.
- `KeepAlive` with `SuccessfulExit=false` restarts after nonzero exit and
  implies `RunAtLoad`. The installed `launchd.plist(5)` says rapidly failing
  jobs are throttled and documents `ThrottleInterval` as a minimum spawn
  interval (10 seconds by default). launchd does not provide the bounded
  exponential policy needed for user-facing failure notices, so the helper
  must debounce notifications and may implement a longer retry/backoff while
  lazy invocation remains available.
- `EnvironmentVariables` accepts literal strings in the plist. Use it only for
  non-secret fixed settings and an explicit `PATH`; never place the bootstrap
  token there. `Program`/`ProgramArguments` likewise contain only non-secret
  executable configuration.
- The helper should log structured, non-secret state through Apple's
  [unified logging API](https://developer.apple.com/documentation/os/logging).
  `StandardOutPath`/`StandardErrorPath` are available but create ordinary files
  and must never receive credential-bearing output. For operator inspection,
  `launchctl print gui/<uid>/<label>` includes origin, current state, execution
  context, and last exit status; the installed manual warns that its output
  shape is diagnostic, not a stable API. `launchctl blame` gives the proximate
  launch reason for a running service.

For readiness failure, the preferred implementation is a signed,
bundle-identified helper/agent using `UNUserNotificationCenter`. Apple requires
an app to
[request notification authorization](https://developer.apple.com/documentation/usernotifications/asking-permission-to-use-notifications)
and exposes the current authorization status through notification settings.
Enrollment must request and verify permission while the user is present.
AppleScript's
[`display notification`](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/DisplayNotifications.html)
is an available shell-level fallback, but its archived contract does not
provide a stable application identity, authorization-state contract, or
delivery acknowledgement. Neither option works as a conspicuous pre-login
signal; unified logs and the next lazy invocation must carry that failure.

## Linux credential store

### Safe interfaces

- Use libsecret against `org.freedesktop.secrets` and identify one item with an
  exact, implementation-owned attribute tuple. The
  [Secret Service specification](https://specifications.freedesktop.org/secret-service/latest/)
  defines collections, items, sessions, `SearchItems`, `Unlock`, `GetSecrets`,
  `CreateItem`, and prompts. libsecret keeps the secret as `SecretValue`
  bytes, so a compiled adapter can store, retrieve, and clear it without a
  process output boundary. A background read must inspect locked results
  without invoking a prompt; if the service returns a locked item or an unlock
  prompt path, return a value-free `locked` status and wait for the session's
  approved unlock path.
- `secret-tool store` is safe for interactive enrollment: current upstream
  source uses a no-echo TTY prompt when stdin is a TTY and otherwise
  [reads the value from stdin](https://github.com/GNOME/libsecret/blob/main/tool/secret-tool.c#L266-L350).
  Do not put the value in a here-string, argv, or shell variable merely to feed
  stdin.
- `secret-tool lookup` is not the unattended adapter: current source
  [unconditionally writes the retrieved value to file descriptor 1](https://github.com/GNOME/libsecret/blob/main/tool/secret-tool.c#L212-L260).
  The libsecret lookup API must return it directly to helper memory instead.
- `secret-tool clear` calls the attribute-matching clear API
  ([source](https://github.com/GNOME/libsecret/blob/main/tool/secret-tool.c#L152-L180)).
  Attributes must be unique to this bootstrap item because clear is a
  predicate, not a secret-confirmed delete.

### Session, unlock, persistence, and headless limits

Secret Service is a D-Bus protocol, not a promise about a provider's backing
store or auto-unlock policy. The specification explicitly allows locked
collections and interactive prompt objects. A concrete provider must be
installed, its chosen collection must be persistent, and its unlock path must
be proven on every supported Linux image.

GNOME Keyring is one valid provider. Its
[upstream README](https://github.com/GNOME/gnome-keyring/blob/main/README)
says the daemon runs in the user session, supports multiple password-protected
keyrings, and also has a session keyring that is never stored to disk. Its PAM
module uses the login authentication token to unlock or start the login
keyring
([source](https://github.com/GNOME/gnome-keyring/blob/main/pam/gkr-pam-module.c#L851-L947)).
When PAM auto-unlock is the chosen mechanism, that makes correct
PAM/display-manager integration and a password-bearing (not automatic) login
operator prerequisites. A separately approved unlock mechanism can replace
that prerequisite; the protocol alone cannot provide one.

Proton adds a second keyring dependency for the encryption key protecting its
persisted provider session. Current Proton Pass CLI defaults on Linux to the
kernel keyring, which needs no graphical session but is cleared at reboot.
`PROTON_PASS_LINUX_KEYRING=dbus` selects persistent D-Bus Secret Service
storage; Proton says it requires D-Bus and fails rather than falling back when
the service is unavailable or locked
([configuration](https://protonpass.github.io/pass-cli/get-started/configuration/#1-keyring-storage-default)).
The host lifecycle must set this non-secret selector on both startup and lazy
paths. After reboot, both the bootstrap item and Proton's local encryption key
must be in a persistent collection and that collection must be unlocked before
repair can succeed.

A console-only, auto-login, container, or otherwise headless host has no
portable unattended persistent-and-unlocked Secret Service contract. It needs
an explicitly supported provider plus an operator-approved unlock mechanism.
Do not silently switch to Proton's filesystem backend: Proton documents that it
stores the plaintext encryption key beside session data
([configuration](https://protonpass.github.io/pass-cli/get-started/configuration/#2-filesystem-storage)).

## Linux startup and failure visibility

- Install a user unit in `$XDG_CONFIG_HOME/systemd/user` (falling back to
  `~/.config/systemd/user`), systemd's user-configuration search path
  ([systemd.unit](https://github.com/systemd/systemd/blob/main/man/systemd.unit.xml#L474-L475)),
  and enable it into the user manager's `default.target`, which systemd defines
  as the main target started when the user manager starts
  ([systemd.special](https://github.com/systemd/systemd/blob/main/man/systemd.special.xml#L1424-L1430)).
  `loginctl enable-linger` instead starts the user manager at boot and keeps it
  after logout
  ([loginctl](https://github.com/systemd/systemd/blob/main/man/loginctl.xml#L186-L195)),
  but lingering does not create a graphical session or unlock Secret Service.
  It is not the default readiness boundary for desktop-backed storage.
- Use `Restart=on-failure` with an explicit `RestartSec` and an explicit
  `StartLimitIntervalSec`/`StartLimitBurst` policy
  ([restart contract](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml#L591-L595),
  [rate-limit contract](https://github.com/systemd/systemd/blob/main/man/systemd.unit.xml#L1212-L1232)).
  The same helper remains callable lazily after systemd exhausts retries.
- Unit environment contains only non-secret backend selectors and paths.
  systemd explicitly says environment variables are unsuitable for secrets
  because they are exposed over D-Bus, propagated down the process tree, and
  not treated as protected data
  ([systemd.exec](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml#L3240-L3249)).
- Keep stdout/stderr credential-free and in the journal.
  `systemctl --user status <unit>` and `journalctl --user-unit=<unit>` are the
  operator surfaces. `OnFailure=` may activate a separate notifier unit when
  readiness enters a failed state
  ([systemd.unit](https://github.com/systemd/systemd/blob/main/man/systemd.unit.xml#L868-L880)).

The native desktop notification path is the
[`org.freedesktop.Notifications.Notify`](https://specifications.freedesktop.org/notification/latest/protocol.html#command-notify)
D-Bus call, either directly or through `notify-send`. It requires a user
session bus and a notification server; the specification does not guarantee a
visible delivery, and no desktop notification is possible for a pre-login or
headless failure. The notifier should emit one non-secret message per failure
state transition, while the journal and lazy command report the durable state.

## Required platform boundary and acceptance checks

The honest common interface is value-free:

1. `store-bootstrap` / `replace-bootstrap` from a no-echo operator input.
2. `delete-bootstrap` by exact metadata.
3. `ensure-ready` returning only a status class and non-secret diagnostic.
4. `inspect` returning presence, store availability/lock state, startup state,
   provider-session health, and last failure without returning any value.
5. `notify-readiness-failure` as best effort.

Credential I/O, startup registration, diagnostics, and notifications remain
platform adapters. Acceptance must exercise these boundaries without treating
a notification as proof:

- fresh enrollment; replacement; metadata-only deletion; helper upgrade;
  missing item; locked/unavailable store; denied ACL/permission;
- provider session already valid, absent, corrupt, expired/revoked, offline,
  and concurrent startup-plus-lazy repair;
- macOS logout/login and full reboot followed by first GUI login;
- Linux user-manager restart, logout/login, full reboot before login, first
  graphical login/PAM unlock, console-only login, missing D-Bus service, locked
  persistent collection, and notification server absent;
- startup retry exhaustion followed by a successful lazy repair; and
  notifications denied, suppressed, or unavailable while status remains
  inspectable.

Unavoidable prerequisites are an enrolled bootstrap token; a persistent,
unlocked per-user native store; the installed helper retaining access after
upgrade; per-user startup enablement; a GUI notification permission/server for
conspicuous notices; and network access when a provider session actually needs
repair. Linux additionally requires a supported Secret Service provider and
working session D-Bus/PAM unlock integration. These are enrollment gates, not
conditions the bootstrap token can repair by itself.

## Unresolved first-party ambiguity

Apple documents trusted-application ACLs but does not state a stable
source-level rule for how a script parent and `/usr/bin/security` are attributed
under every current macOS release, nor how an independently updated helper's
identity survives every ACL migration. The Secret Service specification does
not mandate persistence, a provider, PAM integration, auto-unlock, or headless
behavior. The desktop notification specifications on both platforms do not
promise visible delivery. Those gaps require per-supported-host enrollment and
reboot acceptance checks; they cannot be hidden behind one portable backend.
