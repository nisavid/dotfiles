---
name: extending-managed-skills
description: Use when reviewing, renaming, editing, overriding, extending, or cleaning up installed skills that may be managed by plugins, lockfiles, upstream repos, generated skill managers, byte-identical local copies, or local extension policies.
---

# Extending Managed Skills

## Overview

Managed skills are upstream artifacts. Keep plugin, lockfile, generated, and
byte-identical upstream copies immutable unless the user explicitly asks to
update them through their owning manager.

When local behavior needs to differ, create or edit a separate user-local
extension skill with strong trigger overlap instead of changing the managed
base skill.

## Ownership Check

Before editing a skill, classify it. Use the commands that fit the current
installation and inspect any manager metadata present on the machine:

```bash
jq -r '.skills | keys[]' ~/.local/state/skills/.skill-lock.json 2>/dev/null
find ~/.codex/plugins/cache -name SKILL.md -print
find ~/.agents/skills .agents/skills -maxdepth 2 -name SKILL.md -print
sha256sum <candidate-skill> <possible-upstream-copy>
```

Treat a local skill that is byte-identical to a plugin, lockfile, generated, or
other manager-owned source as an orphaned upstream copy, not local policy.

## Extension Pattern

For managed-skill behavior changes:

- Keep the base skill immutable.
- Use an action-led extension name that describes the local behavior.
- Match the base skill's trigger terms and the exact phrases users say.
- State the base skill it extends and that it applies after the base skill.
- Rename old local extension skills instead of leaving compatibility shims,
  unless another agent or tool still depends on the old name.

Recommended shape:

```markdown
---
name: local-extension-name
description: Use when [same or narrower trigger as base skill, plus exact user phrases]
---

# Local Extension Name

This skill extends `<base-skill-name>`.

Read the base skill first. Then apply these local modifications:

- ...
```

## Discovery Rules

Skill loading is not transitive. A base skill firing does not automatically
load its extension. If an extension must apply whenever a base skill applies,
its description must include the base skill name, base trigger language, and
the local failure mode it prevents.

## Cleanup Policy

Before deleting or moving skills, classify each copy as plugin-managed,
lockfile-managed, repo-local, user-local, generated, or orphaned. Preserve
discoverability for agents that do not load Codex plugins. Remove an orphaned
copy only when losing that discovery path is acceptable.

## Common Mistakes

- Editing plugin cache skills directly.
- Editing lockfile-managed skills outside their manager.
- Treating a byte-identical upstream copy as local policy.
- Creating an extension whose trigger does not overlap the base skill.
- Leaving old compatibility shims that compete with the canonical skill.
