# Agent Instructions

This repository is the chezmoi source for managed dotfiles. `.chezmoiroot` is `home`, so only `home/` deploys to `$HOME`; repository-root files like this one govern work on the repository itself.

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage labels, verbatim: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` plus `docs/adr/`, with per-area glossaries under `docs/`. See `docs/agents/domain.md`.
