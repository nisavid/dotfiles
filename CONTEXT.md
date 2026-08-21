# Managed Dotfiles

This repository declares desired state for Ivan's machines — shells, agent harnesses, credential plumbing — as a chezmoi source tree and deploys it with `chezmoi apply`.

## Language

**Source state**:
The declaration tracked in this repository under `home/`, in chezmoi's source-file naming.
_Avoid_: templates repo, config repo

**Deployed state**:
The files chezmoi renders into `$HOME` on a managed machine; it changes only when `chezmoi apply` runs, so it can lag merged source state.
_Avoid_: installed copies, live config

**Encrypted partial**:
An `.age`-encrypted fragment holding private values, decrypted and merged into rendered config at apply time.
_Avoid_: secret file, private snippet

## Area glossaries

- [Process-Scoped Secret Injection](./docs/secret-injection/CONTEXT.md) — grants selected credentials to individual consumer processes without creating ambient shell credentials
- [Global Agent Equipment](./docs/agent-equipment/CONTEXT.md) — defines portable desired state, harness coverage outcomes, and operation dispositions across global agent harnesses

## Relationships

- **Hindsight (external)**: the reusable lifecycle implementation lives in [nisavid/agents `tooling/hindsight`](https://github.com/nisavid/agents/tree/main/tooling/hindsight); this repository holds only an encrypted consumer binding.
- **Global Agent Equipment → source state**: the equipment catalog selects provider routes; chezmoi deploys their portable source and narrow overlays.
- **Global Agent Equipment → GitHub Issues**: [#44–#61](https://github.com/nisavid/dotfiles/issues?q=is%3Aissue+label%3Aagent-equipment) record the decision history and design work; the durable architecture, schemas, evidence, acceptance contract, and implementation handoff live under `docs/agent-equipment/`.
