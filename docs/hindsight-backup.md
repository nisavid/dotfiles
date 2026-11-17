# Inspect supplied backup observations

`hindsight-backup` describes a complete, explicitly supplied backup publication
and checks pure transition proposals. It reads no default store. A successful
inspection means that the supplied document matches the supported wire shape
and the supplied expected binding. Supplier acceptance, history currentness,
recoverability, current service readiness, and incident policy remain
unqualified, including when the input calls an observation successful or ready.

The maintained implementation is
`home/private_dot_local/lib/hindsight-backup/observations.py`; the thin command is
`home/private_dot_local/bin/executable_hindsight-backup`. Both use Python's
standard library. Existing Hindsight target-selection rules keep these targets
ignored during ordinary chezmoi operations. This procedure requires no installed
binding, database, service, account, or credentials.

## Invoke the source command

Supply UTF-8 JSON files explicitly:

```sh
python3 -I -B -S home/private_dot_local/bin/executable_hindsight-backup inspect \
  --publication publication.json --expected-binding expected-binding.json
```

Use `--format text` for an introductory qualification statement followed by the
same complete JSON result formatted for reading. The machine form is the
default. Exit status is zero for an observed document or a structural proposal,
and two for unavailable input, rejected proposals, or invalid command arguments.
There is no aggregate healthy verdict. An unknown or unavailable incident source
stays visible even if the supplied incident list is empty. Publication times and
readiness observation times are displayed as supplied; no elapsed-time or
freshness rule is inferred.

```sh
python3 -I -B -S home/private_dot_local/bin/executable_hindsight-backup validate-transition \
  --previous previous.json --proposed proposed.json \
  --expected-binding expected-binding.json --transition transition.json
```

The expected binding is a closed object with `scope` and `binding`, copied from
the independently selected intended binding, not automatically from the input:

```json
{
  "scope": {"installation_id": "example", "backup_target_id": "example-target"},
  "binding": {
    "method_revision": {"kind": "method", "id": "example-method", "revision": 1},
    "writer_binding_revision": {"kind": "writer", "id": "example-writer", "revision": 1},
    "response_policy_ref": null
  }
}
```

A matching binding is a comparison of supplied data, not authentication. The
command reads regular files only, with an 8 MiB limit per file. This is a
supported-input resource bound, not a backup size, cadence, or retention policy.
Malformed JSON, duplicate object keys, nonfinite values, wrong primitive types,
unknown or missing fields, unsupported versions, duplicate record identities,
and incompatible bindings are unavailable. No partial publication is returned
on rejection. Input I/O failures produce `input_unavailable` without echoing
file contents or low-level diagnostics.

## Version 1 wire shape

The closed publication has `schema: "hindsight.backup.observations"`, integer
`version: 1`, and these fields:

| Field | Shape |
| --- | --- |
| `scope`, `binding` | Exactly the two objects in the expected-binding example. |
| `revision` | Nonnegative integer; booleans are rejected. |
| `publication` | `{publication_id, previous_revision, transition_ref}`. Revision zero has a null previous revision; later revisions name the preceding integer. This is structural, not proof of bootstrap or intact history. |
| `published_at` | RFC 3339 UTC timestamp using `Z` or `+00:00`. |
| `attempts`, `latest_attempt_id` | Unique attempts and a matching latest-started ID, or an empty list and null. |
| `verified_copy` | Availability envelope containing a copy or `{ "kind": "none_observed" }`. |
| `route_readiness` | Availability envelope containing a readiness observation. |
| `incidents` | Unique incident records. |
| `incident_source` | Availability envelope whose available value is `{ "kind": "incident_set_observed" }`. |

A reference is closed `{kind, id, revision}`: kind and ID are nonempty text;
revision is a nonnegative integer, nonempty opaque text, or null. Method and
writer revisions use this reference shape everywhere. Text excludes control
characters and surrogate code points. An availability envelope is closed
`{state, reason_code, evidence_ref, value}`. Available observations have null
reason, a reference, and a typed value. Unknown/unavailable observations have a
nonempty reason, nullable evidence, and null value. Presence of evidence is not
verification of it.

| Record | Closed fields and states |
| --- | --- |
| Attempt | `attempt_id`, nullable `capture_id`, reference `method_revision`, UTC `started_at`, `stage`, `outcome`, reference `evidence_ref`, integer `record_revision`. Stages: accepted, capturing, transferring, verifying, finished. Finished outcomes: succeeded, failed, cancelled. Other stages: pending or unknown. |
| Copy | `copy_id`, `capture_id`, references `represented_state_ref`, `coverage_ref`, `remote_object_ref`, `transfer_outcome_ref`, `retrieved_equality_ref`, `restore_compatibility_ref`, `method_revision`; UTC `available_for_recovery_at`; nullable `supersedes_copy_id`. A present copy has no `kind` field. |
| Readiness | `verdict` (ready/unavailable/unknown), UTC `observed_at`, references `service_context_ref`, `executable_ref`, `dependencies_ref`, `session_readiness_ref`, nullable `freshness_rule_ref`. The containing envelope's evidence reference identifies the supplied observation. Current readiness always remains unknown in this reader. |
| Incident | `incident_id`, integer `record_revision`, `condition_code`, reference `subject_ref`, `condition_state` (observed/cleared/unknown), `resolution` (unresolved/resolved), reference `evidence_ref`, `action_state`, nullable `action_ref`, `delivery_observations`. |
| Delivery | `delivery_id`, `stage` (submitted/received/handled/acknowledged/outcome_unknown), reference `evidence_ref`. IDs are unique within their incident; distinct observation IDs preserve earlier delivery facts. |

Action states are unselected, none_required, awaiting_authorization, authorized,
running, outcome_unknown, and completed. States other than unselected require
an action reference. The reader displays these supplied states; it does not
establish that an action was authorized, performed, or completed. These concrete
wire choices describe this pure source interface; authoritative supplier and
persistence integrations still need their own accepted contracts.

A non-null readiness evidence reference identifies the complete envelope,
including its availability state and reason. Changing any fact requires a
distinct reference. A null reference explicitly means that no observation
identity was supplied; it never establishes an identified or qualified result.

## Check a transition proposal

The transition declaration is closed `{kind, subject_id}`. Each proposal needs
the next consecutive publication revision and new publication and transition
identities. It preserves scope, binding, and every unrelated field and record.
No pruning, new history, replay, reconciliation, or persistence is performed.

| Kind | Permitted structural change |
| --- | --- |
| `start_attempt` | Append the named accepted/pending attempt at record revision zero and move the latest-started pointer to it. |
| `observe_attempt` | Change the named attempt with new evidence and the next record revision; preserve identity, method, start time, an established capture ID, and the latest-started pointer. Stages cannot regress; terminal outcomes cannot change; unknown outcomes cannot reset to pending. |
| `publish_readiness` | Replace only the supplied readiness observation. `subject_id` is null; current readiness remains unknown. |
| `open_incident` | Append the named observed/unresolved incident with unselected action, no delivery observations, and record revision zero. Recurrence grouping remains the supplier's responsibility. |
| `observe_incident` | Update evidence and optionally condition state for the named unresolved incident, preserving action, resolution, and delivery observations. |
| `observe_delivery` | Append distinct delivery observations to the named incident with new evidence and the next record revision. It cannot authorize an action or resolve a condition. |

`subject_id` is nonempty text except for readiness. New attempts must match the
publication's method binding. Existing record order and prior delivery
observations remain intact. `publish_verified_copy` is refused with
`copy_acceptance_unassessed`: supplied reference labels cannot prove matching
capture/object evidence or coverage ordering. `observe_action` and
`resolve_incident` are refused with `policy_acceptance_unassessed`. Other kinds
are unsupported. A `proposal` has `qualified: false` and `persisted: false`.
It is not compare-and-swap success, duplicate-result recognition, or authority
to perform an external operation.

## Verify and consume the procedure

```sh
python3 -B -m unittest discover -s tests -p test_hindsight_backup_observations.py -v
git diff --check
```

The tests exercise explicit bytes/bindings, transition proposals, and the actual
source command using synthetic files. They do not qualify database publication,
concurrency, restore, continuity, provider readiness, notifications, or backup
operation. Before consuming this procedure, record the reviewed repository
commit and read this guide and its implementation from that revision. Return
the actual inspection result and its supplied scope/publication identity to
the existing operating handoff; an acknowledgment is not incident resolution.

Publisher and recovery work must separately supply original-result recognition,
history/restore reconciliation, qualified copy and state ordering, service
context and freshness, incident/action policy, retention/deletion, and an
accepted operating interface. This command does not create those suppliers or
read credentials, discover configuration, access PostgreSQL, capture or upload
data, acknowledge, resume, change services, or write state.
