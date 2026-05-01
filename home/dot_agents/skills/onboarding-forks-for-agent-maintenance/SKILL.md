---
name: onboarding-forks-for-agent-maintenance
description: Use when preparing a fork for agent-maintained upstream syncs, especially before the first broad sync or when no repo-local fork policy, divergence inventory, or sync gates exist.
---

# Onboarding Forks For Agent Maintenance

## Overview

Before agents sync a modified fork, make intended local contracts explicit. This skill creates repo-local guidance; do not put project-specific contracts in this global skill.

## Discover The Fork

Read before writing policy:

1. Identify remotes, protected branches, direct upstream, source upstream when different, and the current upstream baseline.
2. Inspect `AGENTS.md`, README, maintainer docs, package manifests, release workflows, generated-artifact rules, and existing local skills.
3. Review commits and PRs since the fork point to separate intentional divergences from incidental drift.
4. Identify generated/runtime artifacts and the source files that own them.
5. Identify validation gates for the surfaces that can regress during syncs.

## Create The Local Policy Set

Add the smallest durable policy set:

- always-loaded agent rule: where the fork policy lives and when to read it;
- canonical divergence inventory: each intentional local contract, why it matters, current paths, baseline, and preservation checks;
- sync policy: required merge method, uncertainty triage, local gate evidence, and PR notes;
- optional config file under `.agents/` for machine-readable pointers to the docs and gates;
- repo-local skill only when a repeated maintenance workflow needs more detail than `AGENTS.md`.

Keep README content user-facing. Put maintainer-only sync rules in maintainer docs, local skills, or `.agents/` config.

## Required Fork Contracts

Record contracts that would be painful to rediscover:

- product, package, binary, service, and namespace names;
- filesystem layout, generated artifacts, and runtime state locations;
- versioning and release identity;
- installer, packaging, updater, and privilege boundaries;
- security and supply-chain gates;
- user-visible behavior that differs from upstream;
- docs that must describe the fork's current behavior accurately.

State current desired behavior. Use history only in a post-mortem or when it explains a live constraint.

## Sync Readiness Check

Broad sync work is ready only when:

- the divergence inventory exists and has a current upstream baseline;
- `AGENTS.md` points agents to the inventory and sync policy;
- validation gates are explicit enough to run before push;
- generated/runtime artifact boundaries are clear;
- uncertainty has a documented destination such as the PR body or maintainer issue.

After onboarding, use `syncing-forks-with-upstream` for actual upstream syncs.

## Common Mistakes

| Mistake | Correction |
| --- | --- |
| Starting a sync before recording local contracts | Create the policy set first. |
| Putting all rules in README | Keep README user-facing and route maintainers to policy docs. |
| Describing one incident as the general rule | Put incident analysis in a post-mortem; keep policy current-state. |
| Treating generated output as policy | Find and document the source files that generate it. |
