# Scope the first implementation slice

Type: grilling
Status: resolved

## Question

What must the first complete implementation slice inventory and reconcile?

## Answer

It inventories every global skill, plugin, and MCP currently visible across
Claude Code, Codex, and Cursor. Only entries explicitly accepted into the
catalog become managed; unknown and stale observations remain reported until
classified. The first slice actively reconciles skills, plugins, and MCPs.
Plugin-provided hooks and other component kinds participate in coverage and
conflict decisions even when their standalone reconciliation is deferred.
MCP definitions may contain commands, URLs, package pins, and secret-variable
names, but never secret values; the existing process-scoped `secret-exec`
boundary remains intact.
