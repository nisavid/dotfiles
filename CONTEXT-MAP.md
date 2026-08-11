# Context Map

## Contexts

- [Hindsight](https://github.com/nisavid/agents/tree/main/tooling/hindsight) —
  reusable lifecycle implementation
- [Process-Scoped Secret Injection](./docs/secret-injection/CONTEXT.md) —
  grants selected credentials to individual consumer processes without
  creating ambient shell credentials
- [Global Agent Equipment](./.scratch/global-agent-equipment/CONTEXT.md) —
  defines portable desired state, provider coverage, and operation disposition
  across global agent harnesses

## Relationships

- **Hindsight → managed dotfiles**: `nisavid/agents` supplies reusable code;
  this repository supplies an encrypted consumer binding.
- **Global Agent Equipment → managed dotfiles**: the equipment catalog selects
  provider routes; chezmoi deploys their portable source and narrow overlays.
