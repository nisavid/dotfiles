# Proton Pass agent and PAT lifecycle

Snapshot date: 2026-07-29. The installed and current upstream release was
[Proton Pass CLI 2.2.3](https://github.com/protonpass/pass-cli/releases/tag/2.2.3).
The findings below use the official CLI documentation, Proton's first-party
support material, and the tagged 2.2.3 source.

Refresh the cited release and behavior before implementation when upstream
contracts may have changed.

## Result

A Proton Pass agent is a personal access token (PAT) with a `PassAgent` flag.
It uses the normal PAT login flow but is classified locally as an agent session,
which makes credential operations require an access reason and emit an
encrypted audit record. It is not a self-administering identity: PAT and agent
sessions are blocked from creating, listing, renewing, deleting, granting, or
revoking PATs. Those operations require a full-user/account-owner CLI session.

Renewal is an in-place, non-overlapping replacement: it preserves grants,
returns a new token, and invalidates the old token immediately. Reliable host
rotation therefore needs a separately created replacement agent, grant replay,
host enrollment and validation, and only then deletion of the old agent.

## Identity and access grants

- The official [`agent` reference](https://protonpass.github.io/pass-cli/commands/agent/)
  defines an agent as a PAT with a flag that enables access logging.
  At login, the CLI exchanges the PAT for session credentials, queries the PAT
  `self` endpoint, and changes the local account type to `AgentSession` when
  that flag is present
  ([source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-auth/src/authenticator.rs#L226-L309)).
  A plain PAT has the same scoped-login mechanism without agent reason/audit
  enforcement.
- New PATs have no resource access until grants are added. A grant targets
  either a whole vault or one item inside a vault and has role `viewer`
  (default), `editor`, or `manager`
  ([configuration](https://protonpass.github.io/pass-cli/get-started/configuration/#access-control),
  [`pat access grant`](https://protonpass.github.io/pass-cli/commands/personal-access-token/#pat-access-grant)).
  A whole-vault grant supplies the vault key; an item grant supplies only the
  selected item key
  ([source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass/src/personal_access_token/grant.rs#L74-L177)).
- `agent create --vault ...` is convenience syntax that applies `viewer`
  vault grants after creating the flagged PAT
  ([source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/commands/agent/create.rs#L27-L57)).
  `agent access grant` can later grant a vault or item with any of the three
  roles. For the intended host identity, choose `viewer` explicitly.
- The web-app AI-agent flow is currently narrower: Proton describes its vault
  grants as read-only and says agents cannot create or edit items
  ([first-party overview](https://proton.me/blog/pass-access-tokens#read-only-vault-access)).
  The CLI nevertheless exposes editor and manager roles and audited mutation
  commands. Treat this as a surface difference, not evidence that every
  app-created agent can be made writable in the app.
- `agent access` exposes grant and revoke but not list. A full-user session can
  inspect an agent's exact vault/item grants, roles, grant share IDs, and grant
  expirations through `pat access list-access --pat-name ...`
  ([PAT reference](https://protonpass.github.io/pass-cli/commands/personal-access-token/#pat-access-list-access),
  [command source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/commands/personal_access_token/access/mod.rs#L31-L111)).
  Revocation takes the access grant's share ID.

## Access reasons and auditing

- An agent session must set `PROTON_PASS_AGENT_REASON` to a non-empty string of
  at most 300 characters. There is no reason flag, file, or stdin surface in
  2.2.3
  ([agent reference](https://protonpass.github.io/pass-cli/commands/agent/#providing-a-reason),
  [validation source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/commands/item/agent_monitor.rs#L25-L52)).
  Automation therefore supplies a non-secret reason in the environment of each
  `pass-cli item view` invocation, for example a stable consumer/profile
  purpose. The reason must not contain a credential value.
- One example in the official agent page says `pass-cli agent item view`, but
  2.2.3 has no `item` subcommand under `agent`
  ([command source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/commands/agent/mod.rs#L78-L130)).
  The audited-command list, validation error example, and actual dispatch path
  establish `pass-cli item view` as the supported form. Do not encode the
  inconsistent example into automation.
- For `item view`, the CLI retrieves and decrypts the item, validates and posts
  the reason as an `ItemRead` monitor event, and only then writes the requested
  field to stdout
  ([source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/commands/item/view.rs#L88-L137)).
  A missing/invalid reason or failed monitor post makes the command fail before
  stdout disclosure, but audit is a client-side action after the read. It is
  therefore observability, not an atomic server-side precondition or proof that
  every completed read was logged.
- The monitor payload contains the reason plus vault/item names, is encrypted
  with the PAT key, and is posted to the monitor endpoint
  ([source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass/src/monitor.rs#L239-L303)).
  `agent monitor <name>` decrypts and displays records to a full-user session;
  an agent session may omit its own name
  ([agent reference](https://protonpass.github.io/pass-cli/commands/agent/#agent-monitor)).

## Expiration, creation, renewal, and revocation

- Expiration is mandatory. The CLI accepts exactly `1d`, `1w`, `1m`, `3m`,
  `6m`, or `1y` for create and renew
  ([PAT reference](https://protonpass.github.io/pass-cli/commands/personal-access-token/#pat-create)).
  The current web app accepts a period in minutes from one hour through one
  year
  ([Proton support](https://proton.me/support/pass-access-tokens#create)).
- A full-user `agent list` or `pat list` shows token expiration; JSON retains
  the exact timestamp. `pat access list-access` also shows each grant's expiry
  in UTC. An agent's own `pass-cli info` shows its token name with an `[Agent]`
  prefix but not its expiry, even though the `self` response contains
  `ExpireTime`
  ([info source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/commands/info.rs#L104-L140),
  [self-response source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass/src/info.rs#L107-L119)).
  Host-side readiness cannot discover approaching agent expiry through the
  current CLI; privileged control-plane inspection is required. No first-party
  source found documents proactive expiry notification or a stable
  expiry-specific CLI error.
- Create reveals the complete token only once
  ([agent reference](https://protonpass.github.io/pass-cli/commands/agent/#agent-create)).
  `agent create` creates the PAT before applying requested vault grants and
  before fetching agent instructions. A grant or instruction-download failure
  can therefore leave a created agent whose one-time token was never printed
  ([source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/commands/agent/create.rs#L27-L65)).
- Renew starts a fresh expiration from now, keeps the agent/PAT identity and
  grants, emits a new token, and makes the old token stop working immediately
  ([agent reference](https://protonpass.github.io/pass-cli/commands/agent/#agent-renew),
  [PAT reference](https://protonpass.github.io/pass-cli/commands/personal-access-token/#pat-renew)).
  In addition, `agent renew` invalidates the old token before fetching the
  external instruction document and before printing the new token; an
  instruction-fetch failure can strand the caller without either usable token
  value
  ([source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/commands/agent/renew.rs#L26-L55)).
  It is not a safe zero-downtime rotation primitive.
- Deleting an agent/PAT is irreversible and Proton documents immediate loss of
  access
  ([agent reference](https://protonpass.github.io/pass-cli/commands/agent/#agent-delete),
  [web-app support](https://proton.me/support/pass-access-tokens#delete)).
  Revoking one access grant removes only that vault/item grant, not the token.
- PAT and agent sessions cannot manage any PAT, including themselves. The
  2.2.3 client blocks create, list, delete, renew, grant, list-access, and
  revoke before sending an API request
  ([guard and tests](https://github.com/protonpass/pass-cli/blob/2.2.3/pass/src/personal_access_token/mod.rs#L43-L205)).
  Rotation requires a full-user/account-owner CLI session; the source does not
  impose a separate organization-admin check at this guard.
- Overlap is available by creating a distinct replacement agent, not by
  renewing the old one. This is an inference from the separate create/list/
  delete interfaces: create the replacement under a distinct name, reproduce
  the old agent's grants, enroll and validate every intended host, then delete
  the old agent. No first-party command clones grants or performs this sequence
  atomically.

## PAT login and provider-session persistence

- PAT login has exactly two documented/built-in token inputs in 2.2.3:
  `PROTON_PASS_PERSONAL_ACCESS_TOKEN` or `--personal-access-token`
  ([login reference](https://protonpass.github.io/pass-cli/commands/login/#personal-access-token-login),
  [credential-provider source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/auth/cli_credential_provider.rs#L20-L51)).
  There is no PAT `_FILE` variable, stdin read, or secure prompt. Programmatic
  process-environment injection is the only built-in surface that keeps the
  value out of argv and, provided it is never typed as a shell command, out of
  shell history. The CLI flag exposes it in argv and can expose it in history.
- Login exchanges the bootstrap PAT for a server session containing access and
  refresh tokens, then stores the session and the PAT decryption key encrypted
  under a host-local key
  ([login source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-auth/src/personal_access_token.rs#L121-L201),
  [session-store source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-auth/src/store.rs#L325-L412),
  [PAT-key source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass/src/first_time_setup.rs#L43-L116)).
  Subsequent item commands use this persisted provider session and do not need
  the bootstrap PAT again.
- Login refuses to replace an already authenticated local session
  ([source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-auth/src/authenticator.rs#L226-L243)).
  Startup/lazy recovery must first probe the existing session with
  `pass-cli info` or `pass-cli test`; if recovery requires a new login, it must
  clean up the unusable local session before supplying the bootstrap PAT.
- Normal `logout` asks the server to invalidate the session, removes the local
  encryption key, and deletes all local session/cache data. `logout --force`
  deletes local material without remote invalidation, so the server-side
  session can remain listed and potentially active
  ([logout reference](https://protonpass.github.io/pass-cli/commands/logout/)).
- Session state is stored under a platform data directory, with
  `PROTON_PASS_SESSION_DIR` providing isolation
  ([configuration](https://protonpass.github.io/pass-cli/get-started/configuration/#session-storage-directory)).
  One directory holds one local session; use separate directories if an owner
  session and host-agent session must coexist on the same machine.
  macOS uses Keychain for the local encryption key. Linux 2.2.3 now defaults
  to the kernel keyring, whose secrets are cleared at reboot; if encrypted
  local data remains but the key is gone, the CLI force-logs out and requires
  login again
  ([configuration](https://protonpass.github.io/pass-cli/get-started/configuration/#linux-keyring-note),
  [source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/features/keyring.rs#L36-L87),
  [reboot recovery source](https://github.com/protonpass/pass-cli/blob/2.2.3/pass-cli/src/features/keyring.rs#L253-L273)).
  `PROTON_PASS_LINUX_KEYRING=dbus` opts into a persistent Secret Service key;
  if that service is locked or unavailable, the CLI fails rather than silently
  falling back. This supersedes the repository's current blanket statement
  that Linux uses desktop Secret Service.

## App-assisted administration

- Proton currently documents access-token administration in the Proton Pass
  web app only; desktop-app and browser-extension support is still described as
  forthcoming
  ([support article](https://proton.me/support/pass-access-tokens#create)).
  The web app can create a token, choose vaults, set the AI-agent flag and
  expiry, inspect activity, change vault access, and delete the token.
- Proton explicitly connects web-created access tokens to Pass CLI use
  ([support article](https://proton.me/support/pass-access-tokens#use)).
  The public material does not establish the reverse interoperability details:
  whether CLI-created agents and item-level/role grants are fully editable in
  the web UI, or whether the web UI can renew a token. Keep the app as the
  privileged choice/inspection surface and the CLI as the host-local session
  surface until those behaviors are verified without exposing credentials.
- CLI provider sessions are stored in CLI-specific local files and keyring
  entries. No first-party source found says that a Proton Pass app session can
  be reused as the CLI's full-user session or provider session.

## Unresolved first-party ambiguity

The public docs say renewal makes the old token stop working and deletion causes
immediate loss of access. The CLI implementation, however, exchanges the PAT
for separately persisted access/refresh session credentials. Neither the public
docs nor the public 2.2.3 source specifies whether already-issued CLI sessions
are invalidated immediately on PAT renewal, PAT expiry, PAT deletion, or grant
revocation; nor do they specify refresh-token lifetime or retry behavior. The
private `muon` dependency owns refresh mechanics. Design fail-closed: do not use
renewal for overlap, verify the replacement session before revocation, and
actively test old-session rejection after revocation during implementation
acceptance.
