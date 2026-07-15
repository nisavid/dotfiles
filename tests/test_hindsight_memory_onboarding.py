from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "home/private_dot_local/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from hindsight_memory_control_plane.onboarding import (
    ONBOARDING_TOPICS,
    OnboardingError,
    OnboardingSession,
    apply_onboarding_plan,
    build_onboarding_plan,
)


class OnboardingTest(unittest.TestCase):
    def test_covers_every_required_topic_one_decision_at_a_time(self):
        self.assertEqual(ONBOARDING_TOPICS, ("machine_archetype", "profiles", "providers", "credentials", "banks", "harnesses", "models", "activation", "import"))
        session = OnboardingSession()
        seen = []
        while (decision := session.next_decision()) is not None:
            seen.append(decision.topic)
            session = session.record(decision.choices[0].id, rationale_code="accepted-recommendation")
        self.assertEqual(tuple(seen), ONBOARDING_TOPICS)

    def test_each_decision_has_two_to_four_exclusive_choices_recommendation_first(self):
        session = OnboardingSession()
        for topic in ONBOARDING_TOPICS:
            decision = session.next_decision()
            self.assertEqual(decision.topic, topic)
            self.assertGreaterEqual(len(decision.choices), 2)
            self.assertLessEqual(len(decision.choices), 4)
            self.assertTrue(decision.choices[0].label.endswith("(Recommended)"))
            self.assertEqual(len({choice.id for choice in decision.choices}), len(decision.choices))
            session = session.record(decision.choices[0].id, rationale_code="accepted-recommendation")

    def test_widget_request_omits_timeout_and_plain_prompt_is_complete(self):
        decision = OnboardingSession().next_decision()
        widget = decision.widget_request()
        self.assertNotIn("autoResolutionMs", widget)
        self.assertNotIn("timeout", widget)
        prompt = decision.plain_prompt()
        self.assertIn(decision.question, prompt)
        for choice in decision.choices:
            self.assertIn(choice.label, prompt)

    def test_record_is_content_free_and_persists_only_non_secret_choice_ids(self):
        session = OnboardingSession()
        decision = session.next_decision()
        session = session.record(decision.choices[0].id, rationale_code="accepted-recommendation")
        entry = session.decision_log[0]
        self.assertEqual(set(entry), {"topic", "choice_id", "rationale_code"})
        self.assertNotIn(decision.question, str(entry))
        self.assertEqual(session.desired_state, {"machine_archetype": decision.choices[0].id})
        with self.assertRaises(OnboardingError):
            session.record("token:secret-value", rationale_code="manual")

    def test_credentials_return_official_operator_action_without_secret_state(self):
        session = OnboardingSession()
        while session.next_decision().topic != "credentials":
            session = session.record(session.next_decision().choices[0].id, rationale_code="accepted-recommendation")
        decision = session.next_decision()
        login = next(choice for choice in decision.choices if choice.operator_actions)
        session = session.record(login.id, rationale_code="official-login")
        self.assertEqual(session.desired_state["credentials"], login.id)
        self.assertEqual(session.operator_actions, login.operator_actions)
        self.assertNotIn("token", str(session.desired_state).lower())

    def test_invalid_out_of_order_or_unknown_choice_fails_closed(self):
        session = OnboardingSession()
        with self.assertRaises(OnboardingError):
            session.record("unknown", rationale_code="manual")
        advanced = session.record(
            session.next_decision().choices[0].id,
            rationale_code="manual",
        )
        future_choice = advanced.next_decision().choices[0].id
        with self.assertRaises(OnboardingError):
            session.record(future_choice, rationale_code="manual")
        with self.assertRaises(OnboardingError):
            session.record(session.next_decision().choices[0].id, rationale_code="contains secret gho_example")

    def test_plan_and_apply_use_controller_digest_gate(self):
        session = OnboardingSession()
        session = session.record(session.next_decision().choices[0].id, rationale_code="accepted-recommendation")
        plan = build_onboarding_plan(session, controller_plan_digest="c" * 64)
        calls = []
        with self.assertRaises(OnboardingError):
            apply_onboarding_plan(plan, approved_plan_digest=None, controller_apply=calls.append)
        apply_onboarding_plan(plan, approved_plan_digest=plan.plan_digest, controller_apply=calls.append)
        self.assertEqual(calls, [plan.to_dict()])


if __name__ == "__main__":
    unittest.main()
