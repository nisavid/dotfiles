# Context Map

## Contexts

- [Hindsight](https://github.com/nisavid/agents/tree/main/tooling/hindsight) —
  reusable lifecycle implementation
- [Process-Scoped Secret Injection](./docs/secret-injection/CONTEXT.md) —
  grants selected credentials to individual consumer processes without
  creating ambient shell credentials

## Relationships

- **Hindsight → managed dotfiles**: `nisavid/agents` supplies reusable code;
  this repository supplies an encrypted consumer binding.
