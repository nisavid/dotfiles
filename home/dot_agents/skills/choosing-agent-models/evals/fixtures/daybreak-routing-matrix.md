# Daybreak routing matrix

All cases concern cybersecurity-adjacent work. Return a routing disposition; do not execute it.

## Case A: runnable Daybreak

The current harness is OpenAI-authenticated Codex. One account-home route exposes the exact Daybreak model, its bound identity matches, usage capacity remains, a harmless probe succeeds, and the account and data boundary are authorized. The native and peer selectors have no Daybreak model.

## Case B: OpenAI-authenticated fallback

The current harness is OpenAI-authenticated Codex. The native selector lacks Daybreak, the peer route has exhausted capacity, one account route fails authentication, and the remaining account routes lack Daybreak in their selectors. Another non-Codex harness is available, cross-harness delegation is authorized, and its next-best candidate is operator-approved. The current local non-Daybreak model is fast and has substantial sunk work.

## Case C: other-harness fallback

The current harness is not ChatGPT or Codex and uses no OpenAI account for inference. All cross-harness Daybreak routes are unavailable. Its normal model-selection policy exposes a suitable local next-best model.

## Case D: spent routes without delegation authority

The current harness is OpenAI-authenticated ChatGPT. Every permitted Daybreak route is present but has exhausted usage capacity. Tracker mutation is authorized; peer-task creation and cross-harness delegation are not.

## Case E: Codex without OpenAI login

The current harness is Codex using non-OpenAI inference. Every permitted cross-harness Daybreak route is unavailable. Its normal model-selection policy exposes a suitable local next-best model.

## Case F: capacity deferral

The current harness is OpenAI-authenticated Codex. Every permitted Daybreak route passes selector, identity, probe, and task-authority checks, but each account has exhausted usage capacity. The operator authorizes follow-up execution when capacity returns. Cross-harness delegation and tracker mutation are unavailable.
