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
`greptile`.

AWS uses the narrower external-process protocol:

```text
secret-exec aws-credential-process aws
```

It emits the AWS credential-process JSON shape only when stdout is not a
terminal. The default AWS profile invokes this interface from
`~/.aws/config`.

Codex, Claude Code, and the generic MCP configuration invoke the same launcher
for credentialed servers. Each child receives only its own credential. Git and
GitHub CLI authentication remain independent of the MCP GitHub token.

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
six references. It is idempotent and does not delete the sources.

Apply the launcher, profiles, AWS configuration, and MCP configuration with
chezmoi. Validate each consumer before retirement. Then run:

```sh
secret-exec-migrate --retire-plaintext
```

Retirement fails while the generic Firecrawl MCP entry still has a URL. A
successful retirement permanently removes the ambient environment file, the
interactive Zsh fragment, and the static AWS credentials file. Rollback may
restore the launcher and consumer configuration, but must not restore ambient
plaintext credentials; repair Proton or re-enter a rotated credential through
the provider's secure flow instead.

## Validation

For each host:

1. Start fresh login, interactive, and non-interactive shells and confirm that
   none of the six managed variable names is present.
2. Run the launcher tests with canary values and confirm traced execution does
   not reveal them.
3. Confirm `aws sts get-caller-identity` succeeds through the default profile.
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
