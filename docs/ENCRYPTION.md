# Encryption

This repository stores private configuration as recipient-encrypted [age](https://age-encryption.org) ciphertext. The configured key uses age's hybrid ML-KEM-768 and X25519 recipient scheme (`age-keygen -pq`). Private plaintext belongs only at its intended target or in a mode-restricted transaction phase.

## Configuration

[`home/.chezmoi.toml.tmpl`](../home/.chezmoi.toml.tmpl) configures age with the committed public recipient and the machine-local identity at `~/.config/age/key.txt`. The identity must remain mode `0600`; [`home/.chezmoiignore`](../home/.chezmoiignore) prevents chezmoi from managing it.

Dot-prefixed ciphertext files are source-only data. Chezmoi ignores them as targets, while templates and the private-skill restore hook can read them.

## Encrypted Sources And Plaintext Targets

- `home/.private-agents.md.age` supplies the private section of `home/dot_codex/private_AGENTS.md.tmpl`. Chezmoi renders the combined policy only to `~/.codex/AGENTS.md`; the `private_` source attribute gives that target mode `0600`.
- `home/.private-git-identities.toml.age` supplies identity data only to the generated Git configuration targets. The public hostname map in `home/.chezmoidata/git-identity.toml` selects the default identity; unmapped hosts use the personal identity.
- Each neutral `home/.private-skill-NN-path.age` and `home/.private-skill-NN-body.age` pair contains one relative skill path and its `SKILL.md`. The pair numbers reveal neither skill name nor destination. The restore transaction validates each pair, installs a mode-`0700` directory at `~/.agents/skills/<path>` with a mode-`0600` `SKILL.md`, and creates the corresponding relative symlink under `~/.claude/skills`.

Do not add a plaintext private partial, identity registry, skill path, or skill body to the source tree.

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

Generate a new post-quantum identity, add its public recipient to the age configuration, and re-encrypt every ciphertext to all active recipients. Verify decryption with each retained identity before removing an old recipient. Do not mix post-quantum and classical recipients on one file because the classical recipient determines the weaker confidentiality boundary.
