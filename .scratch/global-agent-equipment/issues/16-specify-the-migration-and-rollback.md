# Specify the migration and rollback

Type: grilling
Status: open
Blocked by: 13, 14, 15

## Question

What ordered, idempotent, and recoverable migration should replace the blanket
Claude skill synchronizer with a catalog-driven projection before removing any
Claude link, then remove only catalog-identified Matt symlinks under
`~/.claude/skills`, install and enable the Claude Matt plugin, and reconcile MCP
and plugin selections? Before mutation, capture every affected provider route,
ownership, installation, enablement, MCP-selection, and plugin-selection state.

On failed verification, restore all of them, including pre-existing plugin
enablement, and uninstall the plugin only when it was absent before migration;
retain reconciled selections only after successful verification.

Never delete, mutate, or follow a pre-existing `~/.agents/skills` entry for a
write. Verify it non-mutatively by type: regular-file bytes and metadata;
directory tree content and applicable metadata; symlink text and, when
resolvable, its resolved target; and the original broken state of a broken
symlink. Migration and rollback must preserve each entry's original type and
state.
