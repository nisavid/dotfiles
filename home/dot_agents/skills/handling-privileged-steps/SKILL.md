---
name: handling-privileged-steps
description: Use when a workflow reaches sudo, password-gated, privileged, or user-owned host mutation, including deploy, install, publish, pacman, systemctl, mount, failed sudo, no-new-privileges, require_escalated, AFK, non-interactive, or faillock-risk situations.
---

# Handling Privileged Steps

## Core Principle

Privilege boundaries are handoff boundaries. Once a step is gated by `sudo`,
password entry, host trust, or user-owned mutation, repeated agent attempts create
risk without creating progress.

## Quick Rules

| Situation | Action |
| --- | --- |
| Non-privileged prep remains | Finish it before handoff |
| First privileged command fails | Stop attempting that privileged step |
| Session is interactive | Hand the exact command to the user |
| Session is AFK/non-interactive | Defer only when valid; continue independent prep |
| Goal depends on the step | Pause the goal until the user resumes |
| User reports completion | Verify the resulting host state yourself |

## Required Handoff

When stopping at a privileged boundary, include:

- Exact workdir
- Exact command for the user to run
- Expected hand-back signal
- Verification you will run afterward
- Clear list of gates still open

## Red Flags

Stop and hand off when you notice:

- `sudo` needs a password, terminal, TTY, or auth agent
- `sudo` fails with no-new-privileges, sandbox, or permission errors
- `pacman`, deploy, install, publish, service, mount, or system paths are involved
- You are considering `require_escalated` just to retry a sudo-gated host mutation
- You already tried this privileged step once in the session
- You think "one more retry" might work without a concrete user-side change

## Common Rationalizations

| Excuse | Reality |
| --- | --- |
| "The sandbox failed, so escalation might work" | For sudo-gated host mutation, the next owner is the user. |
| "The goal says persist until done" | Persistence means preparing the handoff and pausing at the trust boundary. |
| "A later fix needs a fresh deploy" | Rebuild and revalidate what you can, then update the same handoff. |
| "It might be transient" | Password, TTY, no-new-privileges, and faillock risk are not transient build failures. |

## AFK Handling

If the session is AFK or non-interactive, do not ask for privileged action yet.
Continue only work that remains valid before the privileged step. Leave a precise
handoff and do not mark deploy/install/runtime validation complete.

## Resume Handling

When the user says they ran the command, do not rerun the privileged command.
Verify the installed, deployed, or live state with read-only or non-privileged
checks where possible, then continue the workflow from the first blocked gate.
