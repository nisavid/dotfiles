"""One-decision-at-a-time, content-free Hindsight onboarding state."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import re
from typing import Any, Callable, Mapping

from .canonical import digest
from .model import deep_freeze, deep_thaw


class OnboardingError(ValueError):
    pass


ONBOARDING_TOPICS = (
    "machine_archetype", "profiles", "providers", "credentials", "banks",
    "harnesses", "models", "activation", "import",
)
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
SECRET = re.compile(r"(?:gh[opusr]_|sk-|password|token|secret|api[_-]?key)", re.IGNORECASE)


@dataclass(frozen=True)
class Choice:
    id: str
    label: str
    description: str
    operator_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    topic: str
    header: str
    question: str
    choices: tuple[Choice, ...]

    def widget_request(self) -> dict[str, Any]:
        return {
            "questions": [
                {
                    "header": self.header,
                    "id": self.topic,
                    "question": self.question,
                    "options": [
                        {"label": choice.label, "description": choice.description}
                        for choice in self.choices
                    ],
                }
            ]
        }

    def plain_prompt(self) -> str:
        options = "\n".join(f"- {choice.label}: {choice.description}" for choice in self.choices)
        return f"{self.question}\n\n{options}"


def _choices(*values: tuple[str, str, str, tuple[str, ...] | None]) -> tuple[Choice, ...]:
    return tuple(Choice(identifier, label, description, actions or ()) for identifier, label, description, actions in values)


DECISIONS = {
    "machine_archetype": Decision("machine_archetype", "Machine", "Which machine archetype should this installation use?", _choices(
        ("balanced-local", "Balanced local (Recommended)", "Prefer on-device services with explicit remote fallbacks.", None),
        ("remote-first", "Remote first", "Prefer approved remote providers to reduce local resource use.", None),
        ("local-only", "Local only", "Forbid third-party hosted providers.", None),
    )),
    "profiles": Decision("profiles", "Profiles", "Which runtime profile layout should be planned?", _choices(
        ("single-engineering", "Single engineering (Recommended)", "Use one ordinary engineering runtime profile.", None),
        ("engineering-personal", "Engineering and personal", "Separate engineering and personal runtime profiles.", None),
        ("disabled", "No profiles", "Leave Hindsight desired state disabled.", None),
    )),
    "providers": Decision("providers", "Providers", "Which provider posture should be planned?", _choices(
        ("current-compatible", "Current compatible (Recommended)", "Keep currently verified provider role bindings.", None),
        ("local-providers", "Local providers", "Plan only locally hosted inference roles.", None),
        ("remote-providers", "Remote providers", "Plan approved remote role bindings.", None),
    )),
    "credentials": Decision("credentials", "Credentials", "How should missing provider credentials be established?", _choices(
        ("official-login", "Official login (Recommended)", "Return the provider's official interactive login as an operator action.", ("Run the provider's official interactive login flow.",)),
        ("existing-locators", "Existing locators", "Use configured credential locators without reading or persisting values.", None),
        ("defer-credentials", "Defer credentials", "Keep dependent providers blocked.", None),
    )),
    "banks": Decision("banks", "Banks", "Which bank posture should be planned?", _choices(
        ("engineering-authority", "Engineering authority (Recommended)", "Plan one authoritative engineering write bank.", None),
        ("engineering-personal-banks", "Engineering and personal", "Add an explicit personal bank beside engineering.", None),
        ("no-banks", "No banks", "Leave all bank materialization disabled.", None),
    )),
    "harnesses": Decision("harnesses", "Harnesses", "Which harness bindings should be rendered?", _choices(
        ("codex-claude-cursor", "Codex, Claude, Cursor (Recommended)", "Render inactive bindings for the three supported harnesses.", None),
        ("codex-only", "Codex only", "Render only the Codex binding.", None),
        ("no-harnesses", "No harnesses", "Render no harness bindings.", None),
    )),
    "models": Decision("models", "Models", "Which model roster should be planned?", _choices(
        ("verified-current", "Verified current (Recommended)", "Keep the verified current roster and block ungated candidates.", None),
        ("minimal-roster", "Minimal roster", "Plan only required profile models.", None),
        ("defer-models", "Defer models", "Leave model installation and activation blocked.", None),
    )),
    "activation": Decision("activation", "Activation", "When should rendered bindings be activated?", _choices(
        ("plan-only", "Plan only (Recommended)", "Render inactive artifacts and require a later exact approval.", None),
        ("defer-activation", "Defer activation", "Do not create an activation proposal yet.", None),
    )),
    "import": Decision("import", "Import", "Which prior-memory import should be projected?", _choices(
        ("inspect-curated", "Inspect curated sources (Recommended)", "Project curated Codex, Claude, and portable sources without applying.", None),
        ("portable-only", "Portable only", "Inspect only portable Markdown or JSONL manifests.", None),
        ("skip-import", "Skip import", "Do not create an import projection.", None),
    )),
}


@dataclass(frozen=True)
class OnboardingSession:
    selections: tuple[tuple[str, str], ...] = ()
    decision_log: tuple[Mapping[str, str], ...] = ()
    operator_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_log", tuple(deep_freeze(value) for value in self.decision_log))

    @property
    def desired_state(self) -> dict[str, str]:
        return dict(self.selections)

    def next_decision(self) -> Decision | None:
        selected = set(dict(self.selections))
        return next((DECISIONS[topic] for topic in ONBOARDING_TOPICS if topic not in selected), None)

    def record(self, choice_id: str, *, rationale_code: str) -> "OnboardingSession":
        decision = self.next_decision()
        if decision is None:
            raise OnboardingError("onboarding is already complete")
        choice = next((value for value in decision.choices if value.id == choice_id), None)
        if choice is None:
            raise OnboardingError("choice is not valid for the current decision")
        if not SAFE_ID.fullmatch(rationale_code) or SECRET.search(rationale_code):
            raise OnboardingError("rationale code must be a non-secret identifier")
        entry = {"topic": decision.topic, "choice_id": choice.id, "rationale_code": rationale_code}
        return OnboardingSession(
            self.selections + ((decision.topic, choice.id),),
            self.decision_log + (entry,),
            self.operator_actions + choice.operator_actions,
        )


@dataclass(frozen=True)
class OnboardingPlan:
    schema_version: int
    desired_state: Mapping[str, str]
    decision_log: tuple[Mapping[str, str], ...]
    operator_actions: tuple[str, ...]
    controller_plan_digest: str
    plan_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "desired_state", deep_freeze(self.desired_state))
        object.__setattr__(self, "decision_log", tuple(deep_freeze(value) for value in self.decision_log))

    def body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "desired_state": deep_thaw(self.desired_state),
            "decision_log": [deep_thaw(value) for value in self.decision_log],
            "operator_actions": list(self.operator_actions),
            "controller_plan_digest": self.controller_plan_digest,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "plan_digest": self.plan_digest}


def build_onboarding_plan(session: OnboardingSession, *, controller_plan_digest: str) -> OnboardingPlan:
    if not re.fullmatch(r"[0-9a-f]{64}", controller_plan_digest):
        raise OnboardingError("controller plan digest must be a lowercase SHA-256 digest")
    body = {
        "schema_version": 1,
        "desired_state": session.desired_state,
        "decision_log": [deep_thaw(value) for value in session.decision_log],
        "operator_actions": list(session.operator_actions),
        "controller_plan_digest": controller_plan_digest,
    }
    return OnboardingPlan(1, session.desired_state, session.decision_log, session.operator_actions, controller_plan_digest, digest(body))


def apply_onboarding_plan(
    plan: OnboardingPlan,
    *,
    approved_plan_digest: str | None,
    controller_apply: Callable[[dict[str, Any]], Any],
) -> str:
    if approved_plan_digest is None or not hmac.compare_digest(approved_plan_digest, plan.plan_digest):
        raise OnboardingError("exact digest-bound onboarding plan approval is required")
    controller_apply(plan.to_dict())
    return plan.plan_digest
