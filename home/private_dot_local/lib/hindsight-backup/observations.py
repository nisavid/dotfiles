"""Pure inspection of explicitly supplied backup observation documents."""

from datetime import datetime
import json
import re


# A supported-input resource bound, independent of backup cadence or retention.
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
STAGES = ("accepted", "capturing", "transferring", "verifying", "finished")
TERMINAL = {"succeeded", "failed", "cancelled"}
GAPS = ["supplier_acceptance_unassessed", "history_currentness_unassessed",
        "copy_recoverability_unassessed", "readiness_freshness_unassessed",
        "incident_policy_unassessed"]


class InvalidDocument(ValueError):
    """An input cannot be interpreted under the supported wire shape."""


def require(condition, code):
    if not condition:
        raise InvalidDocument(code)


def closed(value, fields):
    require(isinstance(value, dict) and set(value) == set(fields.split()), "object_shape")


def text(value):
    require(isinstance(value, str) and bool(value.strip())
            and all(ord(c) >= 32 and not 0x7F <= ord(c) <= 0x9F
                    and not 0xD800 <= ord(c) <= 0xDFFF for c in value),
            "invalid_text")


def integer(value):
    require(type(value) is int and value >= 0, "invalid_revision")


def reference(value, nullable=False):
    if nullable and value is None:
        return
    closed(value, "kind id revision")
    text(value["kind"])
    text(value["id"])
    revision = value["revision"]
    if revision is not None:
        if type(revision) is int:
            integer(revision)
        else:
            text(revision)


def timestamp(value):
    text(value)
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", value)
            is not None, "invalid_utc_timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidDocument("invalid_utc_timestamp") from error


def unique_records(value, identity, validator):
    require(isinstance(value, list), "record_list")
    ids = set()
    for record in value:
        validator(record)
        require(record[identity] not in ids, "duplicate_identity")
        ids.add(record[identity])
    return ids


def attempt(value):
    closed(value, "attempt_id capture_id method_revision started_at stage outcome evidence_ref record_revision")
    text(value["attempt_id"])
    if value["capture_id"] is not None:
        text(value["capture_id"])
    reference(value["method_revision"])
    timestamp(value["started_at"])
    integer(value["record_revision"])
    require(isinstance(value["stage"], str) and value["stage"] in STAGES, "attempt_stage")
    require(isinstance(value["outcome"], str) and value["outcome"] in (TERMINAL if value["stage"] == "finished"
                                 else {"pending", "unknown"}), "attempt_outcome")
    reference(value["evidence_ref"])


def verified_copy(value):
    if value == {"kind": "none_observed"}:
        return
    closed(value, "copy_id capture_id represented_state_ref coverage_ref remote_object_ref "
           "transfer_outcome_ref retrieved_equality_ref restore_compatibility_ref "
           "available_for_recovery_at method_revision supersedes_copy_id")
    for key in ("copy_id", "capture_id"):
        text(value[key])
    if value["supersedes_copy_id"] is not None:
        text(value["supersedes_copy_id"])
        require(value["supersedes_copy_id"] != value["copy_id"], "copy_self_supersession")
    for key in ("represented_state_ref", "coverage_ref", "remote_object_ref", "transfer_outcome_ref",
                "retrieved_equality_ref", "restore_compatibility_ref", "method_revision"):
        reference(value[key])
    timestamp(value["available_for_recovery_at"])


def readiness(value):
    closed(value, "verdict observed_at service_context_ref executable_ref dependencies_ref "
           "session_readiness_ref freshness_rule_ref")
    require(isinstance(value["verdict"], str) and value["verdict"] in {"ready", "unavailable", "unknown"}, "readiness_verdict")
    timestamp(value["observed_at"])
    for key in ("service_context_ref", "executable_ref", "dependencies_ref", "session_readiness_ref"):
        reference(value[key])
    reference(value["freshness_rule_ref"], nullable=True)


def delivery(value):
    closed(value, "delivery_id stage evidence_ref")
    text(value["delivery_id"])
    require(isinstance(value["stage"], str) and value["stage"] in {"submitted", "received", "handled", "acknowledged", "outcome_unknown"},
            "delivery_stage")
    reference(value["evidence_ref"])


def incident(value):
    closed(value, "incident_id record_revision condition_code subject_ref condition_state resolution "
           "evidence_ref action_state action_ref delivery_observations")
    for key in ("incident_id", "condition_code"):
        text(value[key])
    integer(value["record_revision"])
    require(isinstance(value["condition_state"], str) and value["condition_state"] in {"observed", "cleared", "unknown"}, "condition_state")
    require(isinstance(value["resolution"], str) and value["resolution"] in {"unresolved", "resolved"}, "incident_resolution")
    require(isinstance(value["action_state"], str) and value["action_state"] in {"unselected", "none_required", "awaiting_authorization",
                                      "authorized", "running", "outcome_unknown", "completed"},
            "action_state")
    reference(value["subject_ref"])
    reference(value["evidence_ref"])
    reference(value["action_ref"], nullable=True)
    require(value["action_state"] == "unselected" or value["action_ref"] is not None,
            "missing_action_reference")
    unique_records(value["delivery_observations"], "delivery_id", delivery)


def incident_source(value):
    require(value == {"kind": "incident_set_observed"}, "incident_source_value")


def envelope(value, validator):
    closed(value, "state reason_code evidence_ref value")
    require(isinstance(value["state"], str) and value["state"] in {"available", "unavailable", "unknown"}, "availability_state")
    if value["state"] == "available":
        require(value["reason_code"] is None, "available_reason")
        reference(value["evidence_ref"])
        validator(value["value"])
    else:
        text(value["reason_code"])
        reference(value["evidence_ref"], nullable=True)
        require(value["value"] is None, "unavailable_value")


def validate_binding(value):
    closed(value, "scope binding")
    closed(value["scope"], "installation_id backup_target_id")
    for field in value["scope"].values():
        text(field)
    closed(value["binding"], "method_revision writer_binding_revision response_policy_ref")
    reference(value["binding"]["method_revision"])
    reference(value["binding"]["writer_binding_revision"])
    reference(value["binding"]["response_policy_ref"], nullable=True)


def parse_json(data):
    require(type(data) is bytes and len(data) <= MAX_DOCUMENT_BYTES, "input_bytes_or_limit")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_key")
            result[key] = value
        return result

    def reject_constant(_):
        raise InvalidDocument("nonfinite_number")

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, InvalidDocument):
            raise
        raise InvalidDocument("invalid_utf8_json") from error


def decode_publication(data, expected):
    """Validate supplied bytes and explicit binding; establish no authority."""
    wanted = parse_json(expected)
    validate_binding(wanted)
    doc = parse_json(data)
    closed(doc, "schema version scope revision publication published_at binding attempts latest_attempt_id "
           "verified_copy route_readiness incidents incident_source")
    require(doc["schema"] == "hindsight.backup.observations" and type(doc["version"]) is int
            and doc["version"] == 1, "unsupported_schema")
    validate_binding({"scope": doc["scope"], "binding": doc["binding"]})
    require(doc["scope"] == wanted["scope"] and doc["binding"] == wanted["binding"], "binding_mismatch")
    integer(doc["revision"])
    closed(doc["publication"], "publication_id previous_revision transition_ref")
    text(doc["publication"]["publication_id"])
    previous = doc["publication"]["previous_revision"]
    require((doc["revision"] == 0 and previous is None)
            or (doc["revision"] > 0 and type(previous) is int
                and previous == doc["revision"] - 1), "previous_revision")
    reference(doc["publication"]["transition_ref"])
    timestamp(doc["published_at"])
    ids = unique_records(doc["attempts"], "attempt_id", attempt)
    require(doc["latest_attempt_id"] is None if not ids else (isinstance(doc["latest_attempt_id"], str)
                  and doc["latest_attempt_id"] in ids),
            "latest_attempt")
    envelope(doc["verified_copy"], verified_copy)
    envelope(doc["route_readiness"], readiness)
    unique_records(doc["incidents"], "incident_id", incident)
    envelope(doc["incident_source"], incident_source)
    return doc


def inspect_backup(publication_bytes, expected_binding_bytes):
    """Describe supplied observations without asserting their authority."""
    try:
        document = decode_publication(publication_bytes, expected_binding_bytes)
        state, reason = "observed", None
    except InvalidDocument as error:
        document, state, reason = None, "unavailable", str(error)
    return {"state": state, "reason_code": reason, "publication": document,
            "qualified": False, "currentness": "unknown", "current_readiness": "unknown",
            "gaps": list(GAPS)}


def validate_transition(previous_bytes, proposed_bytes, expected_binding_bytes, transition_bytes):
    """Return a structurally constrained proposal, never a publication result."""
    try:
        old = decode_publication(previous_bytes, expected_binding_bytes)
        new = decode_publication(proposed_bytes, expected_binding_bytes)
        change = parse_json(transition_bytes)
        closed(change, "kind subject_id")
        text(change["kind"])
        if change["kind"] == "publish_readiness":
            require(change["subject_id"] is None, "readiness_subject")
        else:
            text(change["subject_id"])
        require(new["revision"] == old["revision"] + 1, "revision_conflict")
        require(new["publication"]["previous_revision"] == old["revision"], "revision_conflict")
        require(new["publication"]["publication_id"] != old["publication"]["publication_id"]
                and new["publication"]["transition_ref"] != old["publication"]["transition_ref"],
                "publication_identity_reused")
        require(change["kind"] != "publish_verified_copy", "copy_acceptance_unassessed")
        require(change["kind"] not in {"observe_action", "resolve_incident"}, "policy_acceptance_unassessed")
        require(change["kind"] in {"start_attempt", "observe_attempt", "observe_delivery", "publish_readiness",
                                    "open_incident", "observe_incident"},
                "unsupported_transition")
        field = {"observe_delivery": "incidents", "open_incident": "incidents",
                 "observe_incident": "incidents", "publish_readiness": "route_readiness"}.get(
            change["kind"], "attempts")
        allowed = {"revision", "publication", "published_at", field}
        if change["kind"] == "start_attempt":
            allowed.add("latest_attempt_id")
        for key in old:
            if key not in allowed:
                require(new[key] == old[key], "unrelated_change")
        if change["kind"] == "start_attempt":
            require(len(new["attempts"]) == len(old["attempts"]) + 1
                    and new["attempts"][:-1] == old["attempts"], "attempt_history_changed")
            added = new["attempts"][-1]
            require(added["attempt_id"] == change["subject_id"] == new["latest_attempt_id"]
                    and added["stage"] == "accepted" and added["outcome"] == "pending"
                    and added["record_revision"] == 0
                    and added["method_revision"] == new["binding"]["method_revision"], "invalid_attempt_start")
        elif change["kind"] == "observe_attempt":
            before, after = changed_record(old["attempts"], new["attempts"], "attempt_id", change["subject_id"])
            for key in ("attempt_id", "method_revision", "started_at"):
                require(after[key] == before[key], "attempt_identity_changed")
            require(before["capture_id"] is None or after["capture_id"] == before["capture_id"],
                    "capture_identity_changed")
            require(STAGES.index(after["stage"]) >= STAGES.index(before["stage"]), "stage_regression")
            require(before["outcome"] not in TERMINAL or after["outcome"] == before["outcome"],
                    "terminal_outcome_changed")
            require(not (before["outcome"] == "unknown" and after["outcome"] == "pending"),
                    "unknown_outcome_reset")
        elif change["kind"] == "open_incident":
            require(len(new["incidents"]) == len(old["incidents"]) + 1
                    and new["incidents"][:-1] == old["incidents"], "incident_history_changed")
            added = new["incidents"][-1]
            require(added["incident_id"] == change["subject_id"] and added["record_revision"] == 0
                    and added["condition_state"] == "observed" and added["resolution"] == "unresolved"
                    and added["action_state"] == "unselected" and added["action_ref"] is None
                    and not added["delivery_observations"], "invalid_incident_start")
        elif change["kind"] in {"observe_delivery", "observe_incident"}:
            before, after = changed_record(old["incidents"], new["incidents"], "incident_id", change["subject_id"])
            changed_field = "delivery_observations" if change["kind"] == "observe_delivery" else "condition_state"
            for key in before:
                if key not in {"record_revision", "evidence_ref", changed_field}:
                    require(after[key] == before[key], "delivery_is_not_action_or_resolution")
            if change["kind"] == "observe_delivery":
                prior = before["delivery_observations"]
                require(len(after["delivery_observations"]) > len(prior)
                        and after["delivery_observations"][:len(prior)] == prior, "delivery_history_changed")
            else:
                require(before["resolution"] == "unresolved", "resolved_incident_requires_reconciliation")
        else:
            require(new["route_readiness"] != old["route_readiness"], "unchanged_readiness")
            before, after = old["route_readiness"], new["route_readiness"]
            if after["evidence_ref"] is not None and after["evidence_ref"] == before["evidence_ref"]:
                require(after == before, "readiness_identity_reused")
        return {"state": "proposal", "reason_code": None, "publication": new,
                "qualified": False, "persisted": False, "gaps": list(GAPS)}
    except InvalidDocument as error:
        return {"state": "rejected", "reason_code": str(error), "publication": None,
                "qualified": False, "persisted": False, "gaps": list(GAPS)}


def changed_record(previous, proposed, identity, subject):
    require(len(previous) == len(proposed), "record_history_changed")
    selected = None
    for before, after in zip(previous, proposed):
        require(before[identity] == after[identity], "record_identity_changed")
        if before[identity] == subject:
            selected = before, after
            require(after["record_revision"] == before["record_revision"] + 1,
                    "record_revision_conflict")
            require(after["evidence_ref"] != before["evidence_ref"], "new_evidence_required")
        else:
            require(before == after, "unrelated_record_change")
    require(selected is not None, "subject_not_found")
    return selected
