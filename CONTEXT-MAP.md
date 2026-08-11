# Context Map

## Contexts

- [Hindsight](https://github.com/nisavid/agents/tree/main/tooling/hindsight) —
  reusable lifecycle implementation
- [Process-Scoped Secret Injection](./docs/secret-injection/CONTEXT.md) —
  grants selected credentials to individual consumer processes without
  creating ambient shell credentials
- [Global Agent Equipment](./.scratch/global-agent-equipment/CONTEXT.md) —
  defines portable desired state, harness coverage outcomes, and operation
  dispositions across global agent harnesses

## Relationships

- **Hindsight → managed dotfiles**: `nisavid/agents` supplies reusable code;
  this repository supplies an encrypted consumer binding.
- **Global Agent Equipment → managed dotfiles**: the equipment catalog selects
  provider routes; chezmoi deploys their portable source and narrow overlays.
- **Global Agent Equipment → GitHub Issues**: [#44–#61](https://github.com/nisavid/dotfiles/issues?q=is%3Aissue+label%3Aagent-equipment)
  record resolved decisions and dependency-ordered open work; the repository
  retains only the domain context, Wayfinder map, and research evidence.
