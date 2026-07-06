# Encryption

Work-specific and other private snippets in this repo are stored encrypted with
[age](https://age-encryption.org) and spliced into their target files at `chezmoi apply`
time. Encryption is passwordless (recipient-based) and **post-quantum**: keys use age's
hybrid ML-KEM-768 + X25519 scheme (`age-keygen -pq`).

## How it works

- chezmoi is configured for age in the generated `~/.config/chezmoi/chezmoi.toml`
  (produced from [`home/.chezmoi.toml.tmpl`](../home/.chezmoi.toml.tmpl) at `chezmoi init`).
  It sets `encryption = "age"`, `[age] command = "age"`, the identity path, and the public
  `recipient`.
- Encrypted partials are armored `.age` files with neutral, dot-prefixed names so chezmoi
  ignores them as targets but they remain readable via the `include` template function:
  - `home/.private-agents.md.age` — the private, work-specific section of the global agent
    instructions, spliced into `home/dot_codex/AGENTS.md.tmpl` via
    `{{ include ".private-agents.md.age" | decrypt }}`.
  - `home/.private-git-email.age` — the work git email, decrypted into
    `home/dot_config/git/config.tmpl` as the global `user.email` default.
- The public `recipient` in the config is safe to commit. The private key is **never**
  committed (`.config/age` is in `home/.chezmoiignore`).

## Where the key lives

`~/.config/age/key.txt` (mode `600`). This text file *is* the armored key:

```
# created: <timestamp>
# public key: age1pq1...        <- recipient (public, also in chezmoi.toml)
AGE-SECRET-KEY-PQ-1...          <- secret identity (KEEP PRIVATE)
```

## Back it up now

Copy `~/.config/age/key.txt` into a password manager and/or an offline encrypted store.
**If this file is lost, the encrypted snippets are unrecoverable** — there is no password
fallback by design.

## Recovery on a new machine

1. `brew install age chezmoi` (or the platform equivalent).
2. Restore `~/.config/age/key.txt` from backup, then `chmod 600 ~/.config/age/key.txt`.
3. `chezmoi init --apply nisavid/dotfiles`

`chezmoi init` generates `~/.config/chezmoi/chezmoi.toml` from `home/.chezmoi.toml.tmpl` (with
the recipient baked in) *before* the first apply, and apply then decrypts the `.age` partials
with the restored key. Without the key, `chezmoi apply` fails on the encrypted includes — this
is expected; only keyed machines can render the private content.

## Rotating the key / adding a machine

Recipient-based age supports multiple recipients. To rotate or add a device key, generate a
new PQ key, add its `age1pq1...` recipient to the `[age] recipients` list in
`home/.chezmoi.toml.tmpl`, and re-encrypt the `.age` partials to all current recipients
(`chezmoi re-add` / `age -r <r1> -r <r2> ...`). Do not mix post-quantum and classical
recipients on the same file — that would weaken confidentiality to the classical recipient.
