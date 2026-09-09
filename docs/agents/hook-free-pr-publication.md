# Install hook-free PR publication

Install the publisher and its sibling writer from a merged dotfiles revision,
remove the former publication-hook registration and script, and verify the
installed workflow on every authorized host. Use this procedure for a targeted
installation or migration; load it before changing a host.

## Supported source

The maintained entry point is
[`publishing-reviewable-prs`](../../home/dot_agents/skills/publishing-reviewable-prs/SKILL.md).
It owns draft creation, stored title/body updates, and draft-to-ready changes
through its explicit helpers.
[`writing-reviewable-pr-descriptions`](../../home/dot_agents/skills/writing-reviewable-pr-descriptions/SKILL.md)
owns composition and the validator those helpers load from the sibling skill.

This backport adapts the hook-free operation and sibling-package layout from
[Provingkit revision `2391269`](https://github.com/nisavid/provingkit/commit/23912695a636d5357e04ba02c61504a866942144).
The earliest corresponding hook-free source is
[`80ed0cd`](https://github.com/nisavid/provingkit/commit/80ed0cddfa094ffbdd30fb83a5ffeedb8380f0e8);
its [source-resync record](https://github.com/nisavid/provingkit/blob/23912695a636d5357e04ba02c61504a866942144/docs/superpowers/research/2026-08-26-mergecraft-statline-source-resync.md#intentionally-excluded-behaviors-and-artifacts)
identifies the personal PreToolUse activation note as outside the portable
publisher.

The dotfiles adaptation retains its standalone creator/updater interface,
writer validation contract, and final-state reporting, including the warning
for a command error followed by the intended stored state. Source naming follows
chezmoi: `scripts/literal_create_reviewable_pr.py` projects as
`scripts/create_reviewable_pr.py`. Use the source filename when running directly
from the repository and the projected filename after installation.

Successor features such as receipts, Task Witness, review-input manifests,
audit/reconciliation, and explicit text-scope arguments are outside this
backport. The supported helper commands and their acceptance checks remain in
the publisher skill.

## Install and verify

1. **Bind the source and hosts.** Record the merged immutable commit and verify
   each intended host from the operator's request and current inventory. Use a
   persistent sibling worktree at that commit; preserve the primary chezmoi
   checkout's branch and dirty state. Point chezmoi at the selected worktree's
   `home/` source root. Source merge, installation, and installed-byte
   verification are separate results.

2. **Check the pair.** Compare the installed publisher and writer with the
   selected source, including the writer's validator modules. If the writer
   differs, include its skill and Claude projection in this targeted
   installation. Confirm both skill directories will remain siblings. Run
   `zsh tests/public-agent-skills.zsh`,
   `zsh tests/platform-portability.zsh`, and `git diff --check` against the
   selected source, along with the task's required reviews.

3. **Snapshot the affected host state privately.** Record the relevant hook
   configuration, symlink destinations, disabled/trusted settings, and intended
   target files before applying. Keep backups and account-specific details
   outside the repository and publication artifacts. Preserve unrelated hooks,
   settings, authentication, and dirty files. If a hook configuration is
   symlinked, inspect its resolved target before choosing the apply operation.

4. **Preview only the selected targets.** Use the current `chezmoi` command help
   to select the merged `home/` source and preview the exact targets below.
   Apply with `--exclude scripts` so unrelated chezmoi lifecycle scripts do not
   run. The exclusion concerns lifecycle scripts; the explicitly selected
   publisher helper files still belong in the installation.

   | Target relative to the host's home directory | Purpose |
   | --- | --- |
   | `.agents/skills/publishing-reviewable-prs` | Publisher skill and helpers |
   | `.claude/skills/publishing-reviewable-prs` | Claude projection |
   | `.codex/hooks.json` | Remove the former publication-hook registration |
   | `.codex/scripts/block_pr_fill.py` | Retire the script through `.chezmoiremove` |
   | `.agents/skills/writing-reviewable-pr-descriptions` | Include when the installed writer differs from the selected source |
   | `.claude/skills/writing-reviewable-pr-descriptions` | Include with the writer |

   Include the former script target only while it exists. After retirement,
   omit it from repeated applies: chezmoi rejects an explicit absent removal
   target as not managed.

   The removal-only
   [`modify_hooks.json.tmpl`](../../home/dot_codex/modify_hooks.json.tmpl)
   owns registration cleanup;
   [`.chezmoiremove`](../../home/.chezmoiremove) owns script retirement. Inspect
   the preview for unrelated changes or local modifications that would be
   overwritten. Resolve those before applying.

5. **Apply and compare.** Recheck the source commit and target state, then apply
   the reviewed target set. Compare installed bytes against the rendered source,
   accounting for chezmoi filename attributes and symlinks. Verify the Claude
   links resolve to the intended skills, the sibling validator is available,
   the retired script is absent, and the relevant maintained hook configuration
   contains no publication-hook registration. Compare the remaining hook and
   settings state with the private snapshot. Leave the rejected hook disabled;
   publication requires no hook activation or trust step.

6. **Exercise the installed workflow without live mutation.** Run the installed
   creator's `--help` and the updater's `preimage --help`, `text --help`, and
   `ready --help`. Exercise validation with fixture bodies and controlled GitHub
   stubs, including a valid sibling writer and a missing sibling writer. The
   latter must stop before mutation. Use the repository's
   [`test_publish_reviewable_pr.py`](../../tests/test_publish_reviewable_pr.py)
   as the behavioral contract; distinguish its source-tree results from tests
   run against the installed files. Do not create or edit a live PR as an
   installation smoke test.

Report the merged commit, each verified host, rendered-to-installed hashes,
projection and hook-retirement checks, behavioral evidence, and any remaining
gate. Installation is complete only when every intended host has current
evidence for that source revision.
