# Specify the migration and rollback

Type: grilling
Status: open
Blocked by: 13, 14, 15

## Question

What ordered, idempotent, and recoverable migration should replace the blanket
Claude skill synchronizer, remove only catalog-identified Matt symlinks under
`~/.claude/skills`, never delete or dereference any entry under
`~/.agents/skills`, install and enable the Claude Matt plugin, reconcile MCP
and plugin selections, and restore the captured pre-migration provider and
ownership state if verification fails? Rollback must uninstall the plugin only
when this migration installed it. The migration and rollback must verify that
every pre-existing `~/.agents/skills` entry preserves its type, symlink text,
resolved target, and content identity.
