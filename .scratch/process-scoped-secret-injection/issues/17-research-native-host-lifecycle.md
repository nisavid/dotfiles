Type: research
Status: resolved

## Question

What current macOS and Linux native credential-store, startup, notification,
and non-interactive access contracts support secure bootstrap storage,
startup-plus-lazy readiness, and conspicuous failure?

## Answer

Both platforms require compiled credential adapters for the strict unattended
read path: their native command-line tools emit retrieved secrets on stdout.
macOS can combine a helper-owned Keychain item, a per-user LaunchAgent, and
UserNotifications. Linux can combine libsecret with a proven persistent,
unlocked Secret Service provider, a systemd user service, and freedesktop
notifications, but reboot readiness cannot precede the provider's session-bus
and unlock prerequisites. Startup and lazy recovery should call one shared
value-free state machine while credential, startup, and notification behavior
remain platform adapters.

See [the native host lifecycle report](../research/native-host-lifecycle.md).
