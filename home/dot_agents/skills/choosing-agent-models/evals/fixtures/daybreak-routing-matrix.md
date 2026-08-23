# Daybreak routing matrix

Cases A through F and H through K concern cybersecurity-adjacent work. Case G concerns unrelated work. Return a routing disposition; do not execute it.

## Case A

The current harness is OpenAI-authenticated Codex. One Codex session-launch surface exposes the exact Daybreak model, its bound identity is authenticated and matches the private catalog, usage capacity remains, and a harmless probe succeeds. The task authorizes that account, data boundary, workspace, required tools, and any external actions. The native and peer selectors have no Daybreak model.

## Case B

The current harness is OpenAI-authenticated Codex. The native selector lacks Daybreak. The peer or sibling selector exposes the exact Daybreak model, but that surface has exhausted capacity. Its complete permitted Codex session-launch inventory contains surfaces Alpha, Beta, and Gamma. Alpha is a local Codex session-launch surface; its bound identity fails authentication. Beta and Gamma are cross-harness Codex surfaces with authenticated bound identities, but neither selector exposes a Daybreak model. Another non-Codex harness is available, cross-harness delegation is authorized, and its next-best candidate is operator-approved. The current local non-Daybreak model is fast and has substantial sunk work.

## Case C

The current harness is not ChatGPT or Codex and uses no OpenAI account for inference. Its native and peer or sibling selectors expose no Daybreak model. Its complete permitted Codex session-launch inventory contains cross-harness surfaces Alpha and Beta. Alpha's bound identity fails authentication. Beta authenticates, but its selector exposes no Daybreak model. Its normal model-selection policy exposes a suitable local next-best model.

## Case D

The current harness is OpenAI-authenticated ChatGPT. Every permitted Daybreak route is present but has exhausted usage capacity. Tracker mutation is authorized; peer-task creation and cross-harness delegation are not.

## Case E

The current harness is Codex without an OpenAI login and uses non-OpenAI inference. Its native and peer or sibling selectors expose no Daybreak model. Its complete permitted Codex session-launch inventory contains cross-harness surfaces Alpha and Beta. Alpha exposes the exact Daybreak model, but its capacity is exhausted. Beta authenticates and exposes the exact model with capacity remaining, but its harmless probe fails. Its normal model-selection policy exposes a suitable local next-best model.

## Case F

The current harness is OpenAI-authenticated Codex. Every permitted Daybreak route passes selector, identity, probe, and task-authority checks, but each account has exhausted usage capacity. The operator authorizes follow-up execution when capacity returns. Cross-harness delegation and tracker mutation are unavailable.

## Case G

The current harness is OpenAI-authenticated Codex. The task is unrelated to cybersecurity: transcribe a supplied non-sensitive meeting title exactly. A permitted Daybreak route is genuinely runnable. The general model-selection matrix exposes a suitable Luna-tier clerical model.

## Case H

The current harness is OpenAI-authenticated Codex. A bounded cybersecurity subtask must execute at the root of a Codex task. The native subagent selector lacks Daybreak. A permitted cross-harness Codex route is fully authorized and genuinely runnable, and the owning workflow is authorized to create a peer or sibling task through that route.

## Case I

The current harness is OpenAI-authenticated Codex. One account-home route exposes the exact Daybreak model, its bound identity authenticates, and usage capacity remains. The task does not authorize that account, workspace, tools, probe, or external actions. No probe has run, and every other permitted Daybreak route is unavailable.

## Case J

The current harness is OpenAI-authenticated Codex, and no permitted Daybreak route is genuinely runnable. Another harness exposes a non-Daybreak candidate that the operator approves as a model. The task does not authorize the target harness or account, its data boundary, workspace, tools, or external actions. Deferral and tracker mutation are unavailable.

## Case K

The current harness is Codex with an OpenAI login but configured for a non-OpenAI inference provider. No permitted Daybreak route is genuinely runnable. Its local next-best model is available, but deferral, cross-harness delegation, and tracker mutation are unavailable.
