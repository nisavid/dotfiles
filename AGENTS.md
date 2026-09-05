# Agent Instructions

This repository is the chezmoi source for managed dotfiles. `.chezmoiroot` is `home`, so only `home/` deploys to `$HOME`; repository-root files like this one govern work on the repository itself.

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage labels, verbatim: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Multi-context: root `CONTEXT-MAP.md` names each context and links its `CONTEXT.md` under `docs/<context>/`; system-wide ADRs live under `docs/adr/`. The map lists in-repo contexts only. See `docs/agents/domain.md`.

When introducing or revising Cryptosacristy or Codiquarium domain concepts in this repository's design work, follow the [shared domain naming convention](docs/research/CRYPTO_RELEASE_OPS_NAMING.md#domain-naming-convention).

## Git and validation

This is a personal `nisavid` project. Use `Ivan D Vasin <ivan@nisavid.io>` for Git work and the `nisavid` GitHub account for repository mutations. Prefix branches with `ivan/`. Use Conventional Commits for commits and pull request titles; `cog.toml` and the repository hooks enforce the policy.

Treat `$HOME/.local/share/chezmoi` as the stable primary checkout. Preserve whichever branch is checked out there: do not switch or detach that checkout unless Ivan explicitly directs the branch change. Perform other branch work in a persistent sibling worktree under `$HOME/.local/share/chezmoi.wt/`.

For every Git-backed task, use `checkpointing-and-publishing-git-work` at the start, at clean checkpoints, and before stopping. Every change requires `git diff --check`.

Before publication, run the test suites that own the touched surface: `zsh tests/public-agent-skills.zsh` for agent skills, `zsh tests/platform-portability.zsh` for deployment bindings, and `zsh tests/privacy-scan.zsh` plus `python3 scripts/privacy-scan --root . --require-age-manifest` for anything touching encrypted or private material. CI runs all of them; local `privacy-scan` needs `age` installed.

Never commit plaintext secrets. Secret-bearing snippets live as `.age` envelopes under `home/`; treat any plaintext credential in the working tree as a stop-and-report gate.
