# Hindsight Local Stack

This repository owns Ivan's machine bindings for the local Hindsight stack.
Reusable implementation, policy, skills, schemas, examples, and tests live in
[`nisavid/agents`](https://github.com/nisavid/agents/tree/main/tooling/hindsight).

## Source boundary

| Classification | Dotfiles-owned assets | Canonical reusable source |
| --- | --- | --- |
| Machine and user specific | `home/.chezmoidata/hindsight.toml`, launchd values, harness socket files, the named profile and bank, local ports, and the account-aware Hatchery failover patch | Not applicable |
| Installation binding | The installed `hindsight-*` launchers, `hindsight-embed-stack.zsh`, and skill links | `tooling/hindsight/bin`, `tooling/hindsight/lib`, `tooling/hindsight/libexec`, and `tooling/hindsight/skills` in `nisavid/agents` |
| Reusable | None duplicated here | The control-plane package, lifecycle implementation, cleanup implementation, skills, PRD, schemas, examples, and tests in `nisavid/agents` |

The configured agents checkout is `~/src/nisavid/agents`. Change
`hindsight.agentsSourceDir` in `home/.chezmoidata/hindsight.toml` if that
checkout moves. Chezmoi renders regular, machine-owned launchers that delegate
to the reusable files in that checkout; the launchd and trusted-file checks do
not need to accept symlinked machine bindings.

## First-time setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), clone the
agents repository at the configured checkout path, and configure the named
profile without placing credentials in process arguments:

```zsh
profile="$(chezmoi execute-template '{{ .hindsight.profile }}')"
bank_id="$(chezmoi execute-template '{{ .hindsight.bank }}')"
api_port="$(chezmoi execute-template '{{ .hindsight.apiPort }}')"

uvx hindsight-embed configure --profile "$profile" --port "$api_port"
uvx hindsight-embed profile set-env "$profile" HINDSIGHT_BANK_ID "$bank_id"
chezmoi apply
hindsight-embed-service install
hindsight-embed-service status
```

Interactive `configure` is intentional: the non-interactive `--env` path
bypasses provider setup and would put credential material at risk of appearing
in process arguments.

## Everyday operation

```zsh
hindsight-embed-service status
hindsight-embed-service status --profile "$profile"
hindsight-embed-service start
hindsight-embed-service restart
hindsight-embed-service stop
hindsight-embed-service logs
```

The managed stack uses the configured named profile, canonical bank, loopback
ports, launchd label, inactive broker socket, and client adapter files. The
account-aware runtime patch remains local because it names Ivan's personal and
work Codex homes plus the private Hatchery fallback.

## Cleanup boundary

`hindsight-embed-single-bank-cleanup` is a destructive, separately invoked
runbook. Its launcher supplies Ivan's bank, legacy profile, archive-source, and
local endpoint bindings to the reusable implementation. `--apply` additionally
requires explicit `HINDSIGHT_CLEANUP_API_TOKEN`,
`HINDSIGHT_CLEANUP_ARCHIVE_ENCRYPT_COMMAND`, and
`HINDSIGHT_CLEANUP_ARCHIVE_DECRYPT_COMMAND` values. Begin with `--dry-run` and
do not run `--apply` without an independently reviewed migration plan.

Live migration remains blocked until the server-backed opaque monotonic
generation contract described by
[`nisavid/agents` issue #11](https://github.com/nisavid/agents/issues/11) is
available and the complete read-only discovery gate passes. Applying these
dotfiles does not perform a migration, activate a harness, or authorize a
memory write.
