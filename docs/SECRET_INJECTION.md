# Process-scoped credential injection

Credentials for AWS and credentialed MCP servers live in a Proton Pass vault
named `cli-secrets`. Chezmoi stores only Proton Pass references and consumer
configuration. Ordinary login, interactive, and non-interactive shells do not
receive these credentials.

## Runtime contract

`secret-exec <profile> -- <command> [args...]` resolves one profile with
`pass-cli`, removes every managed credential name inherited from the parent,
exports only the selected profile, and replaces itself with the target command.
The supported profiles are `aws`, `context7`, `firecrawl`, `github`, and
`greptile`. The `github` profile resolves the `github-mcp` Proton item; it does
not replace the GitHub CLI login.

AWS uses the narrower external-process protocol:

```text
secret-exec aws-credential-process aws
```

It emits the AWS credential-process JSON shape only when stdout is not a
terminal. The default AWS profile invokes this interface from
`~/.aws/config`.

Codex, Claude Code, the generic MCP configuration, and OpenCode invoke the same
launcher for credentialed servers. Each child receives only its own credential.
Git and GitHub CLI authentication remain independent of the MCP GitHub token.
Every credential-bearing `npx` launch uses an exact audited package version.

## Automatic command shims

Commands listed in `~/.config/secret-exec/commands.env` have managed shims in
`~/.local/lib/secret-exec/bin`. That directory precedes ordinary command
directories on the managed `PATH`. A shim resolves the first later executable
with the same name, then launches it through the mapped `secret-exec` profile.

The current command mapping is:

```text
k9s=aws
sz=aws
```

Consequently, a terminal or application that resolves `k9s` or `sz` through the
managed `PATH` runs the real executable with only the AWS profile. An
application that uses an absolute path bypasses command lookup and therefore
bypasses the shim. The dispatcher rejects missing, duplicate, malformed, and
recursive mappings rather than launching a consumer without the intended
profile.

The managed command map, shim directory, and later `PATH` targets are trusted
user configuration. The dispatcher preserves normal `PATH` semantics, including
relative and user-owned entries; it does not defend against another process
that can modify the user's dotfiles, shims, or target executables. Do not place
shared or otherwise untrusted directories before the intended target.

## Proton Pass layout

The dedicated vault contains five login items:

| Item | Proton field | Runtime variable |
| --- | --- | --- |
| `aws` | username | `AWS_ACCESS_KEY_ID` |
| `aws` | password | `AWS_SECRET_ACCESS_KEY` |
| `github-mcp` | password | `GITHUB_PERSONAL_ACCESS_TOKEN` |
| `context7` | password | `CONTEXT7_API_KEY` |
| `firecrawl` | password | `FIRECRAWL_API_KEY` |
| `greptile` | password | `GREPTILE_API_KEY` |

Every supported host must install the same supported `pass-cli` release, log in
to Proton Pass, and keep the CLI session unlocked for unattended MCP and AWS
processes. This deliberately trades unattended availability for the ability of
any process running as the same operating-system user to invoke `pass-cli`.
Host account isolation remains the security boundary.

## Migration and activation

Run the importer only on a trusted host with the existing local credential
files still present:

```sh
secret-exec-migrate
```

The importer verifies that duplicate sources agree, creates missing Proton
items without placing values in arguments or temporary files, and verifies all
six references. If an existing item differs, the importer stops; reconcile it
through a secure Proton interface because the CLI update command places field
values in process arguments. Once the legacy sources are gone, the importer can
verify that references resolve but cannot infer whether a provider rotated a
credential. It is idempotent and does not delete the sources.

Apply the launcher, profiles, AWS configuration, and MCP configuration with
chezmoi. Validate each consumer before retirement. Then run:

```sh
secret-exec-migrate --retire-plaintext
```

Retirement fails unless every managed consumer has the exact process-scoped
binding, including the absence of URL or header fields where local launchers
replace remote MCP bindings. It also rejects additional `environment.d` or Zsh
fragments that export known credential names and any stale Firecrawl CLI
credential file. The hardened Zsh loader and canonical profile set are
required. A successful retirement permanently removes the ambient environment
file, the interactive Zsh fragment, and the static AWS credentials file.
Rollback may restore the launcher and consumer configuration, but must not
restore ambient plaintext credentials; repair Proton or re-enter a rotated
credential through the provider's secure flow instead.

## Validation

For each host:

1. Start fresh login, interactive, and non-interactive shells and confirm that
   none of these scrubbed variable names is present: `AWS_ACCESS_KEY_ID`,
   `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`,
   `GITHUB_PERSONAL_ACCESS_TOKEN`, `CONTEXT7_API_KEY`, `FIRECRAWL_API_KEY`, and
   `GREPTILE_API_KEY`.
   Also confirm known retired local names such as `CODEX_GITHUB_PAT` and
   `FOSSA_API_KEY` are absent on hosts that previously defined them.
2. Run the launcher tests with canary values and confirm traced execution does
   not reveal them.
3. Confirm `AWS_SHARED_CREDENTIALS_FILE=/dev/null aws sts get-caller-identity`
   succeeds through the default profile, proving that `credential_process` is
   used without a static credentials file.
4. Start each credentialed MCP server through its configured client and perform
   a non-destructive authenticated operation.
5. Confirm the retired files are absent and no managed configuration contains a
   credential-bearing URL or value.

Never print, trace, diff, log, or paste a credential value while validating.

## Rotation

Rotate one provider at a time. Firecrawl is first whenever its URL form or a
trace may have exposed the current value.

1. Create the replacement credential at the provider without revoking the old
   credential.
2. Update the matching Proton item through a secure Proton interface.
3. Validate the consumer on every supported host without printing the value.
4. Revoke the old credential at the provider.
5. Revalidate the consumer and confirm ordinary shells remain clean.

For AWS, rotate the access-key ID and secret-access key as one pair. For GitHub,
rotate the MCP token without changing the GitHub CLI keyring session.
