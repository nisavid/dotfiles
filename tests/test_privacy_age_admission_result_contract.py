from __future__ import annotations

import json
import re
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/privacy-age-admission-result-v1.md"
FIXTURE = ROOT / "tests/fixtures/privacy-age-admission-result-v1.json"
WORKFLOW = ROOT / ".github/workflows/privacy-age-integrity.yml"
DELIVERY_EVENTS = ("opened", "reopened", "synchronize", "ready_for_review", "edited")

COMMIT_ID = re.compile(r"[0-9a-f]{40}\Z")
RESULT_KEYS = {
    "version",
    "repository",
    "base_commit",
    "head_commit",
    "protected_paths",
    "outcome",
    "receipt_required",
}
OUTCOMES = {
    "no_protected_paths_changed": (False, ()),
    "owner_admission_verified": (True, ("nonempty",)),
}


def validate_result(result: dict[str, object]) -> None:
    if set(result) != RESULT_KEYS:
        raise AssertionError("result fields are not the closed v1 set")
    if result["repository"] != "nisavid/dotfiles":
        raise AssertionError("result repository is not bound")
    if result["version"] != "privacy-age-admission-result/v1":
        raise AssertionError("result version is not the closed v1 contract")
    for field in ("base_commit", "head_commit"):
        value = result[field]
        if not isinstance(value, str) or COMMIT_ID.fullmatch(value) is None:
            raise AssertionError(f"{field} is not an exact commit")
    paths = result["protected_paths"]
    if not isinstance(paths, list) or any(
        not isinstance(path, str) for path in paths
    ):
        raise AssertionError("protected_paths is not a string list")
    if paths != sorted(set(paths)):
        raise AssertionError("protected_paths is not sorted and unique")
    outcome = result["outcome"]
    if outcome not in OUTCOMES:
        raise AssertionError("unknown result outcome")
    receipt_required = result["receipt_required"]
    if not isinstance(receipt_required, bool):
        raise AssertionError("receipt_required is not boolean")
    expected_receipt, path_shape = OUTCOMES[outcome]
    if receipt_required != expected_receipt:
        raise AssertionError("receipt flag does not match outcome")
    if path_shape == () and paths:
        raise AssertionError("empty outcome carries protected paths")
    if path_shape == ("nonempty",) and not paths:
        raise AssertionError("protected outcome has no protected paths")


def validate_result_for_head(result: dict[str, object], expected_head: str) -> None:
    validate_result(result)
    if result["head_commit"] != expected_head:
        raise AssertionError("result is bound to a different head")


class PrivacyAgeAdmissionResultContractTests(TestCase):
    def test_contract_names_the_closed_result_vocabulary_and_boundaries(self) -> None:
        contract = CONTRACT.read_text(encoding="utf-8")
        for phrase in (
            "no_protected_paths_changed",
            "owner_admission_verified",
            "repository",
            "base_commit",
            "head_commit",
            "protected_paths",
            "receipt_required",
            "Duplicate",
            "out-of-order",
            "trusted Actions workflow is advisory",
        ):
            self.assertIn(phrase, contract)

    def test_fixture_examples_obey_the_empty_and_nonempty_decision_table(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(document["version"], "privacy-age-admission-result/v1")
        examples = document["examples"]
        self.assertEqual([example["name"] for example in examples], [
            "ordinary-no-protected-transition",
            "protected-transition-with-owner-admission",
        ])
        for example in examples:
            with self.subTest(example=example["name"]):
                validate_result(example["result"])

    def test_result_validator_rejects_closed_contract_violations(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        ordinary = document["examples"][0]["result"]
        protected = document["examples"][1]["result"]
        invalid_results = {
            "unknown outcome": ordinary | {"outcome": "indeterminate"},
            "receipt on empty transition": ordinary | {"receipt_required": True},
            "paths on empty transition": ordinary | {"protected_paths": ["README.md"]},
            "missing protected paths": protected | {"protected_paths": []},
            "receipt omitted for protected transition": protected
            | {"receipt_required": False},
            "duplicate paths": protected
            | {"protected_paths": ["docs/ENCRYPTION.md", "docs/ENCRYPTION.md"]},
            "unsorted paths": protected
            | {
                "protected_paths": [
                    "scripts/privacy_age_integrity_gate.py",
                    "docs/ENCRYPTION.md",
                ]
            },
            "foreign repository": ordinary | {"repository": "attacker/dotfiles"},
            "malformed commit": ordinary | {"head_commit": "not-a-commit"},
        }
        for name, result in invalid_results.items():
            with self.subTest(name=name):
                with self.assertRaises(AssertionError):
                    validate_result(result)

    def test_empty_outcome_cannot_be_relabelled_after_head_changes(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        result = document["examples"][0]["result"]
        with self.assertRaisesRegex(AssertionError, "different head"):
            # The result is structurally valid only for the exact head it
            # names; the App must recompute rather than reuse it for a new head.
            validate_result_for_head(result, "f" * 40)

    def test_app_contract_names_every_head_event_and_delivery_guards(self) -> None:
        contract = CONTRACT.read_text(encoding="utf-8")
        for event in DELIVERY_EVENTS:
            self.assertIn(f"`{event}`", contract)
        for phrase in ("for every supported pull-request", "idempotent"):
            self.assertIn(phrase, contract)

    def test_trusted_workflow_preserves_events_and_exact_verifier_inputs(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for event in DELIVERY_EVENTS:
            self.assertRegex(workflow, rf"\b{event}\b")
        self.assertIn("group: privacy-age-boundary-${{ github.event.pull_request.number }}", workflow)
        self.assertIn("cancel-in-progress: true", workflow)
        for argument in (
            "--base-commit \"$PRIVACY_BASE_SHA\"",
            "--head-commit \"$PRIVACY_HEAD_SHA\"",
            "--repository \"$PRIVACY_REPOSITORY\"",
        ):
            self.assertIn(argument, workflow)
        self.assertIn("trusted-base/scripts/privacy_age_integrity_gate.py", workflow)
        self.assertNotIn("untrusted-head/scripts/privacy_age_integrity_gate.py", workflow)
