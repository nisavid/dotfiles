---
name: hindsight-memory-onboarding
description: Use when interactively configuring or reviewing managed Hindsight machine archetypes, profiles, providers, credentials, banks, harnesses, models, activation, and prior-memory import choices.
---

# Hindsight Memory Onboarding

Guide one decision at a time and turn the accepted non-secret choices into a
controller plan. Do not mutate Hindsight or active harness configuration during
questioning.

## Question Loop

1. Start or resume `hindsight_memory_control_plane.onboarding.OnboardingSession`.
2. Ask only `next_decision()`. Cover machine archetype, profiles, providers,
   credentials, banks, harnesses, models, activation, and import in that order.
3. Present two to four mutually exclusive choices. Put the recommendation first
   and label it `(Recommended)`.
4. When a user-input widget is available, call it with
   `Decision.widget_request()`. Omit `autoResolutionMs` entirely. Wait
   indefinitely for Ivan's answer; never auto-resolve or infer it.
5. When no widget is available, send `Decision.plain_prompt()` as a plain
   question and wait for the answer before continuing.
6. Record only the selected choice ID and a non-secret rationale code. Never
   persist question text, free-form secret values, tokens, passwords, or
   authentication output.
7. Return official provider login flows as explicit operator actions. Do not
   collect credentials or replace an official login with a custom token flow.

## Plan And Apply

After the requested decisions are complete, build the desired-state proposal
with `build_onboarding_plan`, binding it to the current controller plan digest.
Show the redacted desired-state diff, operator actions, and exact plan digest.

Stop before mutation. Apply only after Ivan approves that exact digest, and use
`apply_onboarding_plan` through the controller gate. Dependency installation,
login, harness activation, imports, and live Hindsight changes remain separate
operator-visible actions and retain their own approval and rollback gates.
