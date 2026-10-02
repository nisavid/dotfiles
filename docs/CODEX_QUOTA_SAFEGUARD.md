# Codex quota safeguard installation

The reusable implementation, tests and runtime operating procedure belong to
`nisavid/agents`, under `tooling/codex-usage-safeguard`. This repository supplies
an opt-in Linux installation adapter. It does not own account credentials,
reset approval decisions, episode history or native app transport discovery.

The default `codexQuotaSafeguard.enabled = false` ignores the launcher and
systemd target and downloads nothing. Ignoring preserves an existing
installation; disabling the selection does not stop or uninstall it. Other
platforms omit the targets and archive even when selected. No after-apply hook
starts a process, enables the unit, reloads systemd or changes MCP configuration.

## Selection and preflight

Keep the consumer selection in machine-local chezmoi data, outside this public
repository. The full public example below uses synthetic paths. Actual account
and thread identities remain in the existing private JSON config, not in this
selection. Secret-bearing source, if later introduced, must use the repository's
encrypted-source and admission procedure.

```toml
[data.codexQuotaSafeguard]
enabled = true
releaseCommit = "FULL_REVIEWED_40_CHARACTER_AGENTS_COMMIT"
archiveSha256 = "SHA256_OF_THAT_COMMIT_ARCHIVE"
configFile = "/home/test-user/.config/codex-quota-safeguard/config.json"
stateDir = "/home/test-user/.local/state/codex-quota-safeguard"
sharedLock = "/home/test-user/.local/state/legacy-shared.lock"
```

Do not use the example paths to replace an existing deployment. The initial
handoff must declare its actual existing state directory and singleton lock.
The launcher refuses a missing directory/lock or a config `sharedLock` that
differs from the declaration. The config must declare `stateDir`, and it must
match the selected existing directory. The legacy `sharedLock` remains
authoritative and must be distinct from `stateDir/observer.lock`, because the
controller acquires both locks. A lock that resolves to that observer path is
rejected. The example therefore places the legacy lock beside the state
directory rather than inside it as `observer.lock`.

The private config must have mode `0600`. The state directory must belong to
the executing user and have mode `0700`; the source-owned preflight validates
these permissions. This adapter never creates, copies, edits, restores, deletes
or changes permissions on the existing config, state or lock. Record adoption
evidence and any required prerequisite repair through the source-owned runbook.

Preserve `nativeContext`, account bindings, policy, pending approvals and reset
keys in the existing private config and state. The reusable implementation can
also require `nodeBinary` and `nativeBridgeScript`; follow the pinned release's
operating procedure. A native pipe is runtime information, not a value to bake
into the systemd target. No installed code may retain a dated task workspace or
package-manager cache path as its implementation dependency.

Before opting in:

1. Review and publish the selected agents revision through its owning workflow.
   Obtain and verify the SHA-256 of
   `https://github.com/nisavid/agents/archive/COMMIT.tar.gz`. The disabled public
   default intentionally has no release pin until such a release is available.
2. Confirm that the pinned release contains `controller.py`, `companion.py`,
   `status.py`, `package.json` and its lockfile. Record the existing state/lock
   identities and the current code revision. Do not initialize a fresh ledger.
3. Preview only the selected targets with `chezmoi diff` or `chezmoi apply
   --dry-run`; use the chosen worktree as source and verify the private data
   selection before any real apply.

The archive is checksum-verified and installed beneath
`~/.local/share/codex-quota-safeguard/releases/COMMIT/`. The launcher names this
immutable revision; it never follows a mutable branch or the live source
checkout. The archive contains the agents repository, with the package beneath
`tooling/codex-usage-safeguard/`.

After the separately approved materialization, install the release's locked
Node dependencies in that package directory with
`npm ci --ignore-scripts --omit=dev`. This is an explicit deployment step with
network access, not an automatic chezmoi hook. Verify the release's runtime
requirements with the configured Node executable and the available Python 3;
do not treat unpacked source as a validated runtime.

## Commands and activation

The installed launcher accepts exactly one of:

```sh
codex-quota-safeguard status
codex-quota-safeguard controller
codex-quota-safeguard companion
```

Each delegates to the corresponding Python entry point with the fixed
`--config` and `--state-dir` values. Health interpretation remains in the source
module. Additional arguments, including state overrides, are rejected.

The systemd file retains the existing `codex-usage-safeguard.service` identity
and launches `controller`. It has restart-on-failure and private file modes,
but installation does not enable/start/restart it. Review the source-owned
handoff procedure before reloading or restarting an already enabled unit;
existing enablement links remain outside this adapter's ownership.

Configure the companion through the normal MCP configuration path only after
its separate approval and integration checks. Its command is the installed
launcher with `companion` as its sole argument. Forward the genuine
`CODEX_APP_TOOLS_PIPE_PATH` via MCP `env_vars` according to the source procedure;
never serialize a discovered socket path as a durable default. A configured MCP
child's startup is not proof of a valid thread/turn registration, delivery
acknowledgement or immediate app-start renewal.

## Upgrade and rollback

Change the reviewed commit and archive checksum together. Materialize and
validate the new release, install its locked dependencies, inspect `status`,
and follow the source-owned controlled restart procedure. ChezMoi does not
prune old release directories. Keep the last verified release and its required
dependencies until rollback is no longer needed.

Rollback selects the prior reviewed commit/checksum and repeats the controlled
handoff only if that release can read the current state schema. It does not
restore historical episode files, approvals or reset keys: those may represent
already delivered actions. Preserve the live ledger and reconcile unknown
outcomes. A schema incompatibility blocks a simple code rollback.

## Validation

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_codex_quota_safeguard_deployment
zsh tests/platform-portability.zsh
git diff --check
```

The deployment suite creates an isolated synthetic home and local archive. It
checks disabled and unsupported selections, release integrity, repeated apply,
three fixed entry points, state/lock binding and preservation of existing
config/episode bytes, modification times and inode identities. No real reset,
pause, systemd operation, MCP registration or account request is performed.
