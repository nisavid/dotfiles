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
- `secret-service://` resolves an exact attribute tuple through the operating
  system's Secret Service API.
- `!ENV` removes an inherited variable without resolving a replacement.

The launcher rejects malformed profiles, loose permissions, unsupported
locators, missing values, duplicate names, and multiline values before starting
the consumer. It disables shell tracing before secret resolution and never
places resolved values in command arguments.

Proton Pass sessions are local to each host. Linux uses the desktop Secret
Service provider for the CLI's local session key; the Secret Service must be
available and unlocked for unattended use.

## Personal-access-token login

`proton-pass-session` validates the existing Proton Pass session first. When a
login is needed, run it through a dedicated `secret-exec` profile whose only
value is the Proton personal access token stored in Secret Service:

```text
secret-exec <session-profile> -- proton-pass-session
```

The helper passes the token through the environment expected by the Proton CLI,
unsets it immediately after login, and verifies the resulting session. The
token is never accepted as a helper argument and must not be stored in the
repository.

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
