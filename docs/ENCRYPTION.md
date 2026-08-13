# Encryption

This repository stores private configuration as recipient-encrypted [age](https://age-encryption.org) ciphertext. The configured key uses age's hybrid ML-KEM-768 and X25519 recipient scheme (`age-keygen -pq`). Private plaintext belongs only at its intended target or in a mode-restricted transaction phase.

## Configuration

[`home/.chezmoi.toml.tmpl`](../home/.chezmoi.toml.tmpl) configures age with the committed public recipient and the machine-local identity at `~/.config/age/key.txt`. The identity must remain mode `0600`; [`home/.chezmoiignore`](../home/.chezmoiignore) prevents chezmoi from managing it.

Dot-prefixed ciphertext files are source-only data. Chezmoi ignores them as targets, while templates and the private-skill restore hook can read them.

## Encrypted Sources And Plaintext Targets

- `home/.private-agents.md.age` supplies the private section of `home/dot_codex/private_AGENTS.md.tmpl`. Chezmoi renders the combined policy only to `~/.codex/AGENTS.md`; the `private_` source attribute gives that target mode `0600`.
- `home/.private-codex-work.toml.age` supplies private Codex writable roots and trusted project paths to the mode-`0600` `~/.codex/config.toml` overlay.
- `home/.private-git-identities.toml.age` supplies hostname selection, identity records, editor preference, branch prefix, and tracking policy to generated configuration targets. Public data contains only a synthetic fixture and the allowed personal fallback.
- `home/.private-machine.toml.age` supplies machine-local checkout paths and identity-bearing GnuPG configuration.
- `home/.private-hindsight.toml.age` supplies the complete Darwin-only Hindsight consumer binding. Public Hindsight data contains only the reusable release pin.
- `home/.private-secret-exec.toml.age` supplies secret-provider locators and command-to-profile bindings. It never contains credential values.
- `home/.private-privacy-denylist.txt.age` supplies exact private identifiers to the local privacy scan. Hosted CI runs the generic scan without decrypting this file.
- `home/.private-prd-01.toml.age` is a source-only private requirements catalog with no plaintext target.
- Each neutral `home/.private-skill-NN-path.age` and `home/.private-skill-NN-body.age` pair contains one relative skill path and its `SKILL.md`. The pair numbers reveal neither skill name nor destination. The restore transaction validates each pair, installs a mode-`0700` directory at `~/.agents/skills/<path>` with a mode-`0600` `SKILL.md`, and creates the corresponding relative symlink under `~/.claude/skills`.

Do not add a plaintext private partial, deployment catalog, identity registry,
skill path, or skill body to the source tree.

Before publication, run both scan layers:

```zsh
python3 scripts/privacy-scan --root . --require-age-manifest
chezmoi decrypt home/.private-privacy-denylist.txt.age |
  python3 scripts/privacy-scan --root . --require-age-manifest --denylist -
```

The scanner reports only a path, line, and rule. It never echoes the matched
value.

### Ciphertext admission

The root `.privacy-age-envelopes.json` is the closed, canonical inventory of
every regular `*.age` source path and its exact SHA-256 digest. Hosted scans
require the inventory and age v1.3.1's structural parser, reject an unlisted,
missing, renamed, malformed, oversized, or byte-changed ciphertext, and still
scan the exact ciphertext bytes for plaintext credential and private-key
canaries. `age-inspect` does not authenticate a payload and cannot by itself
distinguish a complete native envelope from a truncated or extended byte
stream.

The manifest is an integrity inventory, not an authenticated admission
receipt. The `pull_request_target` boundary executes only verifier and scanner
code from the exact trusted base commit and treats the pull-request checkout as
data. It rejects any candidate change to ciphertexts, this inventory, the
recipient configuration, admission or scanning code, encryption policy, or any
workflow. A legitimate rotation therefore requires local identity-backed
admission plus an explicit owner-controlled ruleset disposition; ordinary pull
requests cannot mint admission authority by editing the candidate manifest.

The v1 repository policy authorizes exactly one post-quantum recipient stanza
per ciphertext. Hosted scanning enforces that public structural invariant;
admission binds the single stanza to the supplied identity by independently
decrypting the exact bytes. To rotate or add a machine, re-encrypt and admit the
repository as a separately reviewed policy change rather than adding an
unaccounted recipient.

After adding, replacing, removing, or re-encrypting any age source, regenerate
the inventory with the machine-local identity outside the repository:

```zsh
python3 scripts/admit-age-envelopes \
  --root . \
  --identity ~/.config/age/key.txt
python3 scripts/privacy-scan --root . --require-age-manifest
```

The admission command requires age v1.3.1, exactly one mode-`0600` post-quantum
identity outside the repository, and exactly one ML-KEM-768+X25519 recipient
stanza. That identity must independently decrypt every exact candidate to EOF. It reads
each candidate once with a 4 MiB limit before atomically and durably replacing
the manifest. It discards plaintext and age diagnostics. The command leaves the
existing manifest unchanged if any path is unsafe, any envelope fails
decryption, or any other validation fails. Review the ciphertext and manifest
together; do not hand-edit a digest to admit bytes that were not validated by
this command. Exit status `2` with `age-envelope manifest durability uncertain`
means the exact new manifest bytes are installed but the directory durability
commit could not be confirmed; inspect the installed manifest and rerun
admission before treating it as durable.

## Source-Only Catalog Editing

Edit a source-only catalog in a mode-`0700` temporary directory with a
mode-`0600` plaintext file. Decrypt without writing plaintext to standard
output, keep editor swap and backup files inside that phase, validate the
catalog, re-encrypt to a temporary ciphertext with the committed recipient,
and atomically replace the source ciphertext. Remove the plaintext phase on
success, failure, or interruption. Never render the catalog into the repository
or a persistent plaintext target.

## Transactional Private-Skill Restore

`home/run_onchange_after_restore-private-skills.sh.tmpl` hashes every ciphertext pair for change detection and passes the pairs to `scripts/private-skill-transaction`. The transaction:

1. Acquires a cooperative lock under `${XDG_STATE_HOME:-~/.local/state}/chezmoi/private-skill-transaction`.
2. Decrypts and validates every pair in a mode-`0700` phase with mode-`0600` files before changing a target.
3. Saves encrypted recovery metadata and snapshots before publishing the replacement set.
4. Installs and verifies every supplied skill and symlink pair. It then records completion and removes recovery state.

The supplied pairs are transactional inputs, not an authoritative inventory. Removed pairs are not pruned automatically. Remove obsolete live skill targets explicitly under separate authorization.

On a catchable failure, the transaction restores the previous set before returning an error. After an interruption, the next transaction acquisition inspects the encrypted recovery pointer: a pending transaction rolls back to the verified old set, while a completed transaction verifies the published set before clearing recovery data. It refuses recovery when live targets conflict with both the recorded old and desired states.

## Key Backup And Recovery

Back up `~/.config/age/key.txt` in a password manager or offline encrypted store. There is no password fallback. Losing every copy makes the ciphertext unrecoverable.

On a new machine:

1. Install age and chezmoi.
2. Restore `~/.config/age/key.txt` and set mode `0600`.
3. Run `chezmoi init --apply nisavid/dotfiles`.

Initialization writes chezmoi's age configuration before apply. With the correct identity, apply renders the private target files and invokes the transactional skill restore. Without it, decryption fails and the private targets cannot be rendered; restore the identity and rerun apply.

## Rotation And Additional Machines

The v1 single-stanza policy supports a reviewed cutover, not a multi-recipient
overlap. Generate a new post-quantum identity, re-encrypt every ciphertext only
to the new recipient, admit the complete repository with that identity, and
verify the new machine before retiring the old identity. Machines retaining
only the old identity cannot decrypt the rotated repository.

An overlap window requires a separately reviewed policy change that raises the
authorized stanza count and updates admission and hosted scanning together.
Never add an extra recipient under the v1 policy, and do not mix post-quantum
and classical recipients because the classical recipient determines the weaker
confidentiality boundary.
