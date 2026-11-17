"""Supplied-document backup inspection; no live backup or provider fixtures."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "home/private_dot_local/lib/hindsight-backup/observations.py"
COMMAND = ROOT / "home/private_dot_local/bin/executable_hindsight-backup"
SPEC = importlib.util.spec_from_file_location("backup_observations", SOURCE)
observations = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observations)


def ref(identity):
    return {"kind": "synthetic", "id": identity, "revision": 1}


def unavailable(reason):
    return {"state": "unavailable", "reason_code": reason,
            "evidence_ref": None, "value": None}


def publication():
    return {
        "schema": "hindsight.backup.observations", "version": 1,
        "scope": {"installation_id": "fixture", "backup_target_id": "fixture-target"},
        "revision": 0,
        "publication": {"publication_id": "publication-0", "previous_revision": None,
                        "transition_ref": ref("bootstrap-observation")},
        "published_at": "2026-11-17T12:00:00Z",
        "binding": {"method_revision": ref("method"),
                    "writer_binding_revision": ref("writer"), "response_policy_ref": None},
        "attempts": [], "latest_attempt_id": None,
        "verified_copy": {"state": "available", "reason_code": None,
                          "evidence_ref": ref("no-copy-observation"),
                          "value": {"kind": "none_observed"}},
        "route_readiness": unavailable("service_context_unbound"),
        "incidents": [], "incident_source": unavailable("source_unbound"),
    }


def encoded(value):
    return json.dumps(value).encode()


def binding(document):
    return encoded({"scope": document["scope"], "binding": document["binding"]})


def attempt(identity="attempt-A", stage="accepted", outcome="pending"):
    return {"attempt_id": identity, "capture_id": None, "method_revision": ref("method"),
            "started_at": "2026-11-17T12:01:00Z", "stage": stage, "outcome": outcome,
            "evidence_ref": ref(identity + "-evidence"), "record_revision": 0}


def incident():
    return {"incident_id": "incident-A", "record_revision": 0, "condition_code": "copy_unavailable",
            "subject_ref": ref("attempt-A"), "condition_state": "observed", "resolution": "unresolved",
            "evidence_ref": ref("incident-observation"), "action_state": "unselected",
            "action_ref": None, "delivery_observations": []}


def successor(previous):
    doc = copy.deepcopy(previous)
    doc["revision"] += 1
    doc["publication"] = {"publication_id": "publication-" + str(doc["revision"]),
                          "previous_revision": previous["revision"],
                          "transition_ref": ref("transition-" + str(doc["revision"]))}
    return doc


def copy_observation():
    value = {"copy_id": "copy-A", "capture_id": "capture-A",
             "available_for_recovery_at": "2026-11-17T10:00:00Z",
             "method_revision": ref("method"), "supersedes_copy_id": None}
    for key, identity in [("represented_state_ref", "state-A"), ("coverage_ref", "coverage-A"),
                          ("remote_object_ref", "object-A"), ("transfer_outcome_ref", "transfer-A"),
                          ("retrieved_equality_ref", "retrieval-A"), ("restore_compatibility_ref", "restore-A")]:
        value[key] = ref(identity)
    return {"state": "available", "reason_code": None, "evidence_ref": ref("copy-observation-A"),
            "value": value}


class SuppliedDocumentTests(unittest.TestCase):
    def test_valid_document_is_observed_without_asserting_currentness(self):
        doc = publication()
        result = observations.inspect_backup(encoded(doc), binding(doc))
        self.assertEqual(result["state"], "observed")
        self.assertEqual(result["publication"], doc)
        self.assertEqual(result["currentness"], "unknown")
        self.assertEqual(result["current_readiness"], "unknown")
        self.assertFalse(result["qualified"])

    def test_invalid_documents_are_unavailable_without_partial_facts(self):
        doc = publication()
        bad_documents = [b'\xff', b'{', encoded(doc).replace(b'"version": 1', b'"version": 1, "version": 1')]
        for change in [lambda d: d.update(version=True), lambda d: d.update(revision=-1),
                       lambda d: d.update(version=2), lambda d: d.update(extra="unexpected"),
                       lambda d: d["scope"].update(installation_id="other"),
                       lambda d: d["publication"].update(previous_revision=-1),
                       lambda d: d.update(latest_attempt_id="missing"),
                       lambda d: d["verified_copy"].update(value={}),
                       lambda d: d["incident_source"].update(state="available")]:
            altered = copy.deepcopy(doc)
            change(altered)
            bad_documents.append(encoded(altered))
        for data in bad_documents:
            with self.subTest(data=data[:100]):
                result = observations.inspect_backup(data, binding(doc))
                self.assertEqual(result["state"], "unavailable")
                self.assertIsNone(result["publication"])
                self.assertFalse(result["qualified"])

    def test_wrong_nested_types_never_escape_as_exceptions(self):
        doc = publication()
        doc["attempts"] = [attempt()]
        doc["latest_attempt_id"] = "attempt-A"
        doc["incidents"] = [incident()]
        locations = [("latest_attempt_id",), ("revision",), ("publication", "previous_revision"),
                     ("verified_copy", "state"), ("verified_copy", "evidence_ref", "revision"),
                     ("attempts", 0, "stage"), ("attempts", 0, "outcome"),
                     ("incidents", 0, "condition_state"), ("incidents", 0, "resolution"),
                     ("incidents", 0, "action_state")]
        for path in locations:
            for wrong in ([], {}, True, 1.2):
                altered = copy.deepcopy(doc)
                target = altered
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = wrong
                with self.subTest(path=path, wrong=wrong):
                    self.assertEqual(observations.inspect_backup(encoded(altered), binding(doc))["state"],
                                     "unavailable")

    def test_start_attempt_is_only_a_proposal_and_keeps_the_prior_copy(self):
        previous = publication()
        proposed = successor(previous)
        proposed["attempts"] = [attempt()]
        proposed["latest_attempt_id"] = "attempt-A"
        result = observations.validate_transition(encoded(previous), encoded(proposed), binding(previous),
                                                  encoded({"kind": "start_attempt", "subject_id": "attempt-A"}))
        self.assertEqual(result["state"], "proposal")
        self.assertFalse(result["persisted"])
        self.assertFalse(result["qualified"])
        self.assertEqual(result["publication"]["verified_copy"], previous["verified_copy"])

    def test_late_attempt_result_cannot_move_latest_or_reopen_terminal_work(self):
        previous = publication()
        previous["attempts"] = [attempt(), attempt("attempt-B")]
        previous["latest_attempt_id"] = "attempt-B"
        proposed = successor(previous)
        proposed["attempts"][0].update(stage="finished", outcome="failed", record_revision=1,
                                        evidence_ref=ref("late-A-failure"))
        declaration = encoded({"kind": "observe_attempt", "subject_id": "attempt-A"})
        result = observations.validate_transition(encoded(previous), encoded(proposed), binding(previous), declaration)
        self.assertEqual(result["state"], "proposal")
        self.assertEqual(result["publication"]["latest_attempt_id"], "attempt-B")
        wrong_pointer = copy.deepcopy(proposed)
        wrong_pointer["latest_attempt_id"] = "attempt-A"
        self.assertEqual(observations.validate_transition(encoded(previous), encoded(wrong_pointer),
                         binding(previous), declaration)["state"], "rejected")
        reopened = successor(proposed)
        reopened["attempts"][0].update(stage="capturing", outcome="pending", record_revision=2,
                                      evidence_ref=ref("fresh-reopening-evidence"))
        result = observations.validate_transition(encoded(proposed), encoded(reopened), binding(previous), declaration)
        self.assertEqual(result["state"], "rejected")
        self.assertEqual(result["reason_code"], "stage_regression")

    def test_terminal_attempt_outcome_cannot_change_with_fresh_evidence(self):
        previous = publication()
        previous["attempts"] = [attempt("attempt-A", "finished", "succeeded")]
        previous["latest_attempt_id"] = "attempt-A"
        proposed = successor(previous)
        proposed["attempts"][0].update(outcome="failed", record_revision=1,
                                      evidence_ref=ref("fresh-different-outcome"))
        result = observations.validate_transition(encoded(previous), encoded(proposed), binding(previous),
                         encoded({"kind": "observe_attempt", "subject_id": "attempt-A"}))
        self.assertEqual(result["state"], "rejected")
        self.assertEqual(result["reason_code"], "terminal_outcome_changed")

    def test_delivery_acknowledgment_preserves_unknown_work_and_unresolved_action(self):
        previous = publication()
        previous["attempts"] = [attempt(stage="transferring", outcome="unknown")]
        previous["latest_attempt_id"] = "attempt-A"
        previous["incidents"] = [incident()]
        proposed = successor(previous)
        proposed["incidents"][0].update(record_revision=1, evidence_ref=ref("ack-observation"))
        proposed["incidents"][0]["delivery_observations"].append(
            {"delivery_id": "delivery-ack", "stage": "acknowledged", "evidence_ref": ref("actual-ack")})
        declaration = encoded({"kind": "observe_delivery", "subject_id": "incident-A"})
        result = observations.validate_transition(encoded(previous), encoded(proposed), binding(previous), declaration)
        self.assertEqual(result["state"], "proposal")
        self.assertEqual(result["publication"]["attempts"][0]["outcome"], "unknown")
        self.assertEqual(result["publication"]["incidents"][0]["resolution"], "unresolved")
        proposed["incidents"][0]["resolution"] = "resolved"
        self.assertEqual(observations.validate_transition(encoded(previous), encoded(proposed),
                         binding(previous), declaration)["state"], "rejected")

    def test_ready_observation_remains_unknown_now_and_cannot_replace_copy_evidence(self):
        previous = publication()
        proposed = successor(previous)
        ready = {"verdict": "ready", "observed_at": "2026-11-17T11:00:00Z",
                 "service_context_ref": ref("before-login"), "executable_ref": ref("executable"),
                 "dependencies_ref": ref("dependencies"), "session_readiness_ref": ref("session-check"),
                 "freshness_rule_ref": None}
        proposed["route_readiness"] = {"state": "available", "reason_code": None,
                                      "evidence_ref": ref("readiness-observation"), "value": ready}
        result = observations.validate_transition(encoded(previous), encoded(proposed), binding(previous),
                         encoded({"kind": "publish_readiness", "subject_id": None}))
        self.assertEqual(result["state"], "proposal")
        inspected = observations.inspect_backup(encoded(proposed), binding(previous))
        self.assertEqual(inspected["publication"]["route_readiness"]["value"]["verdict"], "ready")
        self.assertEqual(inspected["current_readiness"], "unknown")
        proposed["verified_copy"] = unavailable("lost_copy")
        result = observations.validate_transition(encoded(previous), encoded(proposed), binding(previous),
                         encoded({"kind": "publish_verified_copy", "subject_id": "claimed-copy"}))
        self.assertEqual(result["reason_code"], "copy_acceptance_unassessed")

    def test_production_cli_reads_only_supplied_files_and_renders_the_same_result(self):
        doc = publication()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "publication.json"
            expected = root / "expected.json"
            source.write_bytes(encoded(doc))
            expected.write_bytes(binding(doc))
            environment = {"PATH": os.defpath, "HOME": temporary, "PYTHONPATH": str(root / "unused")}
            command = [sys.executable, "-I", "-B", "-S", str(COMMAND), "inspect",
                       "--publication", str(source), "--expected-binding", str(expected)]
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            machine = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(machine.returncode, 0, machine.stderr)
            result = json.loads(machine.stdout)
            self.assertEqual(result, observations.inspect_backup(encoded(doc), binding(doc)))
            human = subprocess.run(command + ["--format", "text"], env=environment,
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(human.returncode, 0, human.stderr)
            self.assertEqual(json.loads(human.stdout.split("\n", 1)[1]), result)
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            missing = subprocess.run([sys.executable, "-I", "-B", "-S", str(COMMAND), "inspect"],
                                     env=environment, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(missing.returncode, 0)

            proposed = successor(doc)
            proposed["attempts"] = [attempt()]
            proposed["latest_attempt_id"] = "attempt-A"
            next_file = root / "proposed.json"
            transition_file = root / "transition.json"
            next_file.write_bytes(encoded(proposed))
            transition_file.write_bytes(encoded({"kind": "start_attempt", "subject_id": "attempt-A"}))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            validate = [sys.executable, "-I", "-B", "-S", str(COMMAND), "validate-transition",
                        "--previous", str(source), "--proposed", str(next_file),
                        "--expected-binding", str(expected), "--transition", str(transition_file)]
            checked = subprocess.run(validate, env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(json.loads(checked.stdout)["state"], "proposal")
            expected.write_bytes(binding({**doc, "scope": {**doc["scope"], "installation_id": "other"}}))
            rejected = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(rejected.returncode, 2)
            self.assertIsNone(json.loads(rejected.stdout)["publication"])
            expected.write_bytes(before["expected.json"])
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_open_and_repeat_incident_preserve_the_same_unresolved_obligation(self):
        previous = publication()
        proposed = successor(previous)
        proposed["incidents"] = [incident()]
        result = observations.validate_transition(encoded(previous), encoded(proposed), binding(previous),
                         encoded({"kind": "open_incident", "subject_id": "incident-A"}))
        self.assertEqual(result["state"], "proposal")
        repeated = successor(proposed)
        repeated["incidents"][0].update(record_revision=1, evidence_ref=ref("repeat-observation"))
        result = observations.validate_transition(encoded(proposed), encoded(repeated), binding(previous),
                         encoded({"kind": "observe_incident", "subject_id": "incident-A"}))
        self.assertEqual(result["state"], "proposal")
        self.assertEqual(len(result["publication"]["incidents"]), 1)
        self.assertEqual(result["publication"]["incidents"][0]["action_state"], "unselected")
        repeated["incidents"][0].update(action_state="authorized", action_ref=ref("unqualified-label"))
        result = observations.validate_transition(encoded(proposed), encoded(repeated), binding(previous),
                         encoded({"kind": "observe_incident", "subject_id": "incident-A"}))
        self.assertEqual(result["state"], "rejected")

    def test_failed_new_attempt_preserves_the_original_recovery_observation(self):
        previous = publication()
        previous["attempts"] = [attempt("attempt-A", "finished", "succeeded"), attempt("attempt-B")]
        previous["latest_attempt_id"] = "attempt-B"
        previous["verified_copy"] = copy_observation()
        proposed = successor(previous)
        proposed["attempts"][1].update(stage="finished", outcome="failed", record_revision=1,
                                      evidence_ref=ref("B-failure"))
        result = observations.validate_transition(encoded(previous), encoded(proposed), binding(previous),
                         encoded({"kind": "observe_attempt", "subject_id": "attempt-B"}))
        self.assertEqual(result["state"], "proposal")
        self.assertEqual(result["publication"]["verified_copy"]["value"]["represented_state_ref"]["id"], "state-A")
        self.assertEqual(result["publication"]["latest_attempt_id"], "attempt-B")
        self.assertFalse(result["qualified"])

    def test_duplicate_records_and_incomplete_copy_evidence_are_unavailable(self):
        doc = publication()
        doc["verified_copy"] = copy_observation()
        cases = []
        incomplete = copy.deepcopy(doc)
        del incomplete["verified_copy"]["value"]["retrieved_equality_ref"]
        cases.append(incomplete)
        duplicated = copy.deepcopy(doc)
        duplicated["attempts"] = [attempt(), attempt()]
        duplicated["latest_attempt_id"] = "attempt-A"
        cases.append(duplicated)
        duplicated = copy.deepcopy(doc)
        duplicated["incidents"] = [incident(), incident()]
        cases.append(duplicated)
        duplicated = copy.deepcopy(doc)
        duplicated["incidents"] = [incident()]
        delivery = {"delivery_id": "duplicate", "stage": "submitted", "evidence_ref": ref("submission")}
        duplicated["incidents"][0]["delivery_observations"] = [delivery, delivery]
        cases.append(duplicated)
        for altered in cases:
            with self.subTest(altered=altered):
                self.assertEqual(observations.inspect_backup(encoded(altered), binding(doc))["state"], "unavailable")

    def test_readiness_replacement_requires_a_new_observation_identity(self):
        previous = publication()
        ready = {"verdict": "ready", "observed_at": "2026-11-17T11:00:00Z",
                 "service_context_ref": ref("after-login"), "executable_ref": ref("executable"),
                 "dependencies_ref": ref("dependencies"), "session_readiness_ref": ref("session"),
                 "freshness_rule_ref": None}
        previous["route_readiness"] = {"state": "available", "reason_code": None,
                                      "evidence_ref": ref("original-readiness-observation"), "value": ready}
        changes = {"verdict": "unknown", "observed_at": "2026-11-17T12:00:00Z",
                   "service_context_ref": ref("before-login"), "executable_ref": ref("new-executable"),
                   "dependencies_ref": ref("new-dependencies"), "session_readiness_ref": ref("new-session"),
                   "freshness_rule_ref": ref("freshness-rule")}
        declaration = encoded({"kind": "publish_readiness", "subject_id": None})
        for field, value in changes.items():
            proposed = successor(previous)
            proposed["route_readiness"]["value"][field] = value
            with self.subTest(field=field):
                result = observations.validate_transition(encoded(previous), encoded(proposed),
                                                         binding(previous), declaration)
                self.assertEqual(result["state"], "rejected")
                self.assertEqual(result["reason_code"], "readiness_identity_reused")
                proposed["route_readiness"]["evidence_ref"] = ref("new-" + field + "-observation")
                result = observations.validate_transition(encoded(previous), encoded(proposed),
                                                         binding(previous), declaration)
                self.assertEqual(result["state"], "proposal")
                self.assertFalse(result["persisted"])
                self.assertFalse(result["qualified"])
                self.assertEqual(observations.inspect_backup(encoded(proposed), binding(previous))["current_readiness"],
                                 "unknown")

    def test_controls_are_rejected_but_ordinary_unicode_remains_supported(self):
        doc = publication()
        for path in [("publication", "publication_id"), ("publication", "transition_ref", "id"),
                     ("incident_source", "reason_code")]:
            for character in ("\x00", "\x1f", "\x7f", "\x85", "\x9f", "\ud800"):
                altered = copy.deepcopy(doc)
                field = altered
                for part in path[:-1]:
                    field = field[part]
                field[path[-1]] = "fixture" + character + "value"
                with self.subTest(path=path, character=repr(character)):
                    result = observations.inspect_backup(encoded(altered), binding(doc))
                    self.assertEqual(result["state"], "unavailable")
                    self.assertIsNone(result["publication"])
        doc["publication"]["publication_id"] = "mémoire-日本語"
        self.assertEqual(observations.inspect_backup(encoded(doc), binding(doc))["state"], "observed")

    def test_nonavailable_readiness_facts_cannot_reuse_an_observation_identity(self):
        declaration = encoded({"kind": "publish_readiness", "subject_id": None})
        cases = [
            ("unknown", "unavailable", "probe_unknown", "probe_failed"),
            ("unknown", "unknown", "probe_unknown", "different_unknown"),
            ("unknown", "unavailable", "probe_unknown", "probe_unknown"),
            ("unavailable", "unknown", "probe_failed", "probe_unknown"),
            ("unavailable", "unavailable", "probe_failed", "different_failure"),
            ("unavailable", "unknown", "probe_failed", "probe_failed"),
        ]
        for old_state, new_state, old_reason, new_reason in cases:
            previous = publication()
            previous["route_readiness"] = {"state": old_state, "reason_code": old_reason,
                                          "evidence_ref": ref("original-observation"), "value": None}
            proposed = successor(previous)
            proposed["route_readiness"].update(state=new_state, reason_code=new_reason)
            with self.subTest(old_state=old_state, new_state=new_state, new_reason=new_reason):
                result = observations.validate_transition(encoded(previous), encoded(proposed),
                                                         binding(previous), declaration)
                self.assertEqual(result["state"], "rejected")
                self.assertEqual(result["reason_code"], "readiness_identity_reused")
                self.assertIsNone(result["publication"])
                proposed["route_readiness"]["evidence_ref"] = ref("replacement-observation")
                result = observations.validate_transition(encoded(previous), encoded(proposed),
                                                         binding(previous), declaration)
                self.assertEqual(result["state"], "proposal")
                self.assertFalse(result["qualified"])
                self.assertFalse(result["persisted"])
                self.assertEqual(observations.inspect_backup(encoded(proposed), binding(previous))["current_readiness"],
                                 "unknown")

    def test_absent_readiness_identity_is_distinct_from_an_identified_observation(self):
        previous = publication()
        previous["route_readiness"] = {"state": "unknown", "reason_code": "no_observation",
                                      "evidence_ref": None, "value": None}
        proposed = successor(previous)
        proposed["route_readiness"].update(state="unavailable", reason_code="source_unbound")
        result = observations.validate_transition(encoded(previous), encoded(proposed), binding(previous),
                         encoded({"kind": "publish_readiness", "subject_id": None}))
        self.assertEqual(result["state"], "proposal")
        self.assertIsNone(result["publication"]["route_readiness"]["evidence_ref"])
        self.assertFalse(result["qualified"])
        self.assertFalse(result["persisted"])


if __name__ == "__main__":
    unittest.main()
