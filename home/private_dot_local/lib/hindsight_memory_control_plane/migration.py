"""Read-only migration discovery and immutable, unapproved shadow planning."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from datetime import datetime
import errno
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any, Callable, Mapping, Sequence

from .adapters import AdapterError
from .canonical import canonical_bytes, digest
from .file_evidence import FileEvidenceError, read_file_evidence, reject_symlink_components
from .model import BankRef, deep_freeze, deep_thaw


class MigrationError(ValueError):
    pass


DIGEST = re.compile(r"[0-9a-f]{64}\Z")
TIMESTAMP = re.compile(r"[0-9]{8}T[0-9]{6}Z\Z")
SEMANTIC_SCOPE = re.compile(r"(?:repo:[a-z0-9][a-z0-9._-]*|scope:active)\Z")
SNAPSHOT_KEYS = {
    "schema_version",
    "endpoint",
    "provider_identity",
    "versions",
    "banks",
    "operations",
    "hooks",
    "schedules",
    "retain_watermarks",
}
BANK_KEYS = {
    "bank_ref",
    "config",
    "stats",
    "scopes",
    "tags",
    "documents",
    "models",
    "directives",
    "invalidated_memories",
}
PACKAGE_KEYS = {
    "schema_version",
    "approved_manifest_digest",
    "artifact_digest",
    "projection_digest",
    "tag_mapping_digest",
    "candidate_provenance_digest",
    "candidate_curation_digest",
    "invalidation_dispositions",
}
COVERAGE_KEYS = {"item_id", "content_digest", "disposition", "reason", "semantic_scope"}
INVALIDATION_KEYS = {"item_id", "disposition", "reason", "reapply_content_digest"}
PLAN_KEYS = {
    "schema_version",
    "kind",
    "approved",
    "mutation_authority",
    "complete",
    "blockers",
    "source_bank",
    "candidate_bank",
    "bindings",
    "coverage",
    "invalidation_dispositions",
    "semantic_diff",
    "operations",
    "legacy_observations_imported",
    "rollback_requirements",
    "cutover",
    "closeout",
    "archive_retirement",
    "plan_digest",
}
BINDING_KEYS = {
    "inventory_digest",
    "offline_package_manifest_digest",
    "offline_package_artifact_digest",
    "projection_digest",
    "tag_mapping_digest",
    "high_water_manifest_digest",
    "invalidation_manifest_digest",
    "source_coverage_digest",
    "candidate_coverage_digest",
    "invalidation_disposition_digest",
    "candidate_provenance_digest",
    "candidate_curation_digest",
    "private_catalog_digests",
    "endpoint_digest",
    "provider_identity_digest",
    "versions_digest",
}
ROLLBACK_REQUIREMENTS = [
    "source_full_bank_export",
    "shadow_full_bank_export",
    "full_schema_backup",
    "disposable_restore_proofs",
    "invalidated_memory_verification",
]
CUTOVER_REQUIREMENTS = {
    "freeze_retain_paths": True,
    "block_new_session_exchange": True,
    "revoke_existing_write_capabilities": True,
    "wait_for_idle_operations": True,
    "capture_final_high_water": True,
    "final_catch_up": True,
    "on_drift": "restart_verification",
}
CLOSEOUT_REQUIREMENTS = {
    "kind": "live-bank-closeout",
    "authority": "separate_digest_bound_approval",
    "archive_deletion_authority": False,
}
ARCHIVE_RETIREMENT_REQUIREMENTS = {
    "kind": "migration-archive-retirement",
    "authority": "separate_digest_bound_approval",
    "requires_accepted_cutover": True,
}


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise MigrationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _identifier(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 256
        or any(character in value for character in "\r\n\0")
    ):
        raise MigrationError(f"{label} must be a bounded identifier")
    return value


def _normalized(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalized(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        items = [_normalized(item) for item in value]
        return sorted(items, key=canonical_bytes)
    return value


def _offline_package_digest(manifest: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in _normalized(manifest).items()
        if key != "approved_manifest_digest"
    }
    return digest(body)


def _read_gate(path: str, label: str) -> dict[str, Any]:
    try:
        evidence = read_file_evidence(path, label, allow_missing=True)
    except FileEvidenceError as error:
        raise MigrationError(str(error)) from None
    if evidence is None:
        return {"exists": False, "digest": None}
    return {"exists": True, "digest": evidence[1]}


def _reject_symlink_components(path: Path, label: str) -> None:
    try:
        reject_symlink_components(path, label, allow_missing=True)
    except FileEvidenceError as error:
        raise MigrationError(str(error)) from None


def _gate_snapshot(paths: Mapping[str, Any]) -> dict[str, Any]:
    required = {"artifact_dir", "completion_marker", "proposal_log"}
    if not isinstance(paths, Mapping) or set(paths) != required:
        raise MigrationError("migration paths are closed")
    return {
        "completion_marker": _read_gate(paths["completion_marker"], "completion marker"),
        "proposal_log": _read_gate(paths["proposal_log"], "proposal log"),
    }


def _retain_watermark_snapshot(reader: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    if not callable(reader):
        raise MigrationError("retain watermark reader is required")
    try:
        value = reader()
    except Exception:
        raise MigrationError("retain watermark snapshot is unavailable") from None
    if not isinstance(value, Mapping):
        raise MigrationError("retain watermark snapshot must be an object")
    return _normalized(value)


def _adapter_generation_snapshot(adapter: Any) -> str:
    reader = getattr(adapter, "read_migration_generation", None)
    if not callable(reader):
        raise MigrationError("adapter migration generation is unavailable")
    try:
        value = reader()
    except Exception:
        raise MigrationError("adapter migration generation is unavailable") from None
    try:
        encoded_value = value.encode("utf-8")
    except (AttributeError, UnicodeEncodeError):
        raise MigrationError("adapter migration generation is unavailable") from None
    if (
        not isinstance(value, str)
        or not value
        or len(encoded_value) > 256
        or not value.isprintable()
    ):
        raise MigrationError("adapter migration generation is unavailable")
    return value


def _with_retain_watermarks(snapshot: Any, watermarks: Mapping[str, Any]) -> Any:
    if not isinstance(snapshot, Mapping):
        return snapshot
    if "retain_watermarks" in snapshot:
        raise MigrationError("adapter snapshot must not contain retain watermarks")
    return {**snapshot, "retain_watermarks": watermarks}


def _mapping(value: Any, label: str, blockers: list[str]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        blockers.append(f"invalid:{label}")
        return None
    return value


def _validate_document(role: str, raw: Any, blockers: list[str]) -> None:
    record = _mapping(raw, f"{role}.documents", blockers)
    if record is None:
        return
    for key in ("document_id", "updated_at", "content_digest"):
        if key not in record:
            blockers.append(f"missing:{role}.documents.{key}")
    if "document_id" in record:
        try:
            _identifier(record["document_id"], "document ID")
        except MigrationError:
            blockers.append(f"invalid:{role}.documents.document_id")
    if "updated_at" in record:
        try:
            parsed = datetime.fromisoformat(str(record["updated_at"]).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except (TypeError, ValueError):
            blockers.append(f"invalid:{role}.documents.updated_at")
    if "content_digest" in record:
        try:
            _sha(record["content_digest"], "document content digest")
        except MigrationError:
            blockers.append(f"invalid:{role}.documents.content_digest")


def _validate_invalidation(role: str, raw: Any, blockers: list[str]) -> None:
    record = _mapping(raw, f"{role}.invalidated_memories", blockers)
    if record is None:
        return
    for key in ("item_id", "source_document_id", "reason_digest", "content_digest"):
        if key not in record:
            blockers.append(f"missing:{role}.invalidated_memories.{key}")
    for key in ("item_id", "source_document_id"):
        if key in record:
            try:
                _identifier(record[key], key.replace("_", " "))
            except MigrationError:
                blockers.append(f"invalid:{role}.invalidated_memories.{key}")
    for key in ("reason_digest", "content_digest"):
        if key in record:
            try:
                _sha(record[key], key.replace("_", " "))
            except MigrationError:
                blockers.append(f"invalid:{role}.invalidated_memories.{key}")


def _snapshot_blockers(snapshot: Any, source_bank: BankRef, candidate_bank: BankRef) -> list[str]:
    blockers: list[str] = []
    if not isinstance(snapshot, Mapping):
        return ["invalid:snapshot"]
    for key in sorted(SNAPSHOT_KEYS):
        if key not in snapshot:
            blockers.append(f"missing:{key}")
    if blockers:
        return blockers
    if set(snapshot) != SNAPSHOT_KEYS:
        blockers.append("invalid:snapshot_keys")
    if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1:
        blockers.append("invalid:schema_version")
    for key in ("endpoint", "provider_identity", "versions", "banks", "operations", "retain_watermarks"):
        _mapping(snapshot[key], key, blockers)
    for key in ("hooks", "schedules"):
        if not isinstance(snapshot[key], list):
            blockers.append(f"invalid:{key}")
    banks = snapshot.get("banks")
    if isinstance(banks, Mapping):
        if set(banks) != {"source", "candidate"}:
            blockers.append("invalid:banks")
        for role, expected in (("source", source_bank), ("candidate", candidate_bank)):
            bank = banks.get(role)
            if not isinstance(bank, Mapping):
                blockers.append(f"missing:banks.{role}")
                continue
            for key in sorted(BANK_KEYS):
                if key not in bank:
                    blockers.append(f"missing:{role}.{key}")
            if set(bank) != BANK_KEYS:
                blockers.append(f"invalid:{role}.bank_keys")
            if bank.get("bank_ref") != expected.to_dict():
                blockers.append(f"invalid:{role}.bank_ref")
            for key in ("config", "stats"):
                if not isinstance(bank.get(key), Mapping):
                    blockers.append(f"invalid:{role}.{key}")
            for key in ("scopes", "tags", "documents", "models", "directives", "invalidated_memories"):
                if not isinstance(bank.get(key), list):
                    blockers.append(f"invalid:{role}.{key}")
            documents = bank.get("documents", [])
            if isinstance(documents, list):
                for document in documents:
                    _validate_document(role, document, blockers)
                identifiers = [item.get("document_id") for item in documents if isinstance(item, Mapping)]
                if len(identifiers) != len(set(identifiers)):
                    blockers.append(f"invalid:{role}.documents.duplicate")
            invalidations = bank.get("invalidated_memories", [])
            if isinstance(invalidations, list):
                for item in invalidations:
                    _validate_invalidation(role, item, blockers)
                identifiers = [item.get("item_id") for item in invalidations if isinstance(item, Mapping)]
                if len(identifiers) != len(set(identifiers)):
                    blockers.append(f"invalid:{role}.invalidated_memories.duplicate")
    operations = snapshot.get("operations")
    if isinstance(operations, Mapping):
        if set(operations) != {"idle", "active"} or type(operations.get("idle")) is not bool or not isinstance(operations.get("active"), list):
            blockers.append("invalid:operations")
        elif not operations["idle"] or operations["active"]:
            blockers.append("operations:not_idle")
    return sorted(set(blockers))


def _high_water(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for role in ("source", "candidate"):
        for document in snapshot["banks"][role]["documents"]:
            rows.append(
                {
                    "bank_role": role,
                    "document_id": document["document_id"],
                    "updated_at": document["updated_at"],
                    "content_digest": document["content_digest"],
                }
            )
    return sorted(rows, key=lambda item: (item["bank_role"], item["document_id"]))


def _invalidations(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for role in ("source", "candidate"):
        for item in snapshot["banks"][role]["invalidated_memories"]:
            rows.append({"bank_role": role, **{key: item[key] for key in ("item_id", "source_document_id", "reason_digest", "content_digest")}})
    return sorted(rows, key=lambda item: (item["bank_role"], item["item_id"]))


def _operation_ids(snapshot: Mapping[str, Any]) -> list[str]:
    result = []
    for operation in snapshot["operations"]["active"]:
        if isinstance(operation, Mapping):
            result.append(str(operation.get("operation_id", operation.get("id", "unknown"))))
        else:
            result.append(str(operation))
    return sorted(result)


def _drift_blockers(before: Mapping[str, Any], after: Mapping[str, Any], before_gate: Any, after_gate: Any) -> list[str]:
    checks = {
        "completion_gate": (before_gate, after_gate),
        "bank_stats": (
            {role: before["banks"][role]["stats"] for role in ("source", "candidate")},
            {role: after["banks"][role]["stats"] for role in ("source", "candidate")},
        ),
        "operation_ids": (_operation_ids(before), _operation_ids(after)),
        "document_high_water": (_high_water(before), _high_water(after)),
        "retain_watermarks": (before["retain_watermarks"], after["retain_watermarks"]),
        "identity": (
            {key: before[key] for key in ("endpoint", "provider_identity", "versions")},
            {key: after[key] for key in ("endpoint", "provider_identity", "versions")},
        ),
    }
    return [f"drift:{name}" for name, values in checks.items() if digest(_normalized(values[0])) != digest(_normalized(values[1]))]


def _package_blockers(manifest: Any, approved_digest: Any) -> list[str]:
    blockers: list[str] = []
    if not isinstance(manifest, Mapping) or set(manifest) != PACKAGE_KEYS:
        return ["offline_package:invalid_manifest"]
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        blockers.append("offline_package:invalid_schema")
    for key in (
        "approved_manifest_digest",
        "artifact_digest",
        "projection_digest",
        "tag_mapping_digest",
        "candidate_provenance_digest",
        "candidate_curation_digest",
    ):
        try:
            _sha(manifest[key], f"offline package {key}")
        except MigrationError:
            blockers.append(f"offline_package:invalid_{key}")
    actual_digest = _offline_package_digest(manifest)
    if (
        not isinstance(approved_digest, str)
        or DIGEST.fullmatch(approved_digest) is None
        or not isinstance(manifest["approved_manifest_digest"], str)
        or not hmac.compare_digest(actual_digest, approved_digest)
        or not hmac.compare_digest(
            manifest["approved_manifest_digest"], actual_digest
        )
    ):
        blockers.append("offline_package:digest_mismatch")
    if not isinstance(manifest["invalidation_dispositions"], list):
        blockers.append("offline_package:invalid_invalidation_dispositions")
    return sorted(set(blockers))


def _coverage_scope(bank: Mapping[str, Any], document: Mapping[str, Any]) -> str:
    candidates: set[str] = set()
    for values in (bank.get("scopes"), bank.get("tags"), document.get("tags")):
        if not isinstance(values, list):
            continue
        candidates.update(
            value
            for value in values
            if isinstance(value, str) and SEMANTIC_SCOPE.fullmatch(value) is not None
        )
    repositories = sorted(value for value in candidates if value.startswith("repo:"))
    if len(repositories) > 1:
        raise MigrationError("migration item has conflicting repository scopes")
    return repositories[0] if repositories else "scope:active"


def _live_coverage(snapshot: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for role in ("source", "candidate"):
        bank = snapshot["banks"][role]
        result[role] = sorted(
            (
                {
                    "item_id": document["document_id"],
                    "content_digest": document["content_digest"],
                    "disposition": "retain",
                    "reason": "stable-live-document",
                    "semantic_scope": _coverage_scope(bank, document),
                }
                for document in bank["documents"]
            ),
            key=lambda item: item["item_id"],
        )
    return result


def _coverage_blockers(snapshot: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    raw_dispositions = manifest["invalidation_dispositions"]
    if isinstance(raw_dispositions, list):
        records = []
        for item in raw_dispositions:
            if not isinstance(item, Mapping) or set(item) != INVALIDATION_KEYS:
                blockers.append("curation:invalid_record")
                continue
            records.append(item)
            try:
                _identifier(item["item_id"], "invalidation item ID")
                _identifier(item["reason"], "invalidation reason")
            except MigrationError:
                blockers.append("curation:invalid_record")
            if item["disposition"] not in {"exclude", "supersede", "reapply"}:
                blockers.append("curation:invalid_disposition")
            if item["disposition"] == "reapply":
                try:
                    _sha(item["reapply_content_digest"], "reapply content digest")
                except MigrationError:
                    blockers.append("curation:invalid_reapply_digest")
            elif item["reapply_content_digest"] is not None:
                blockers.append("curation:unexpected_reapply_digest")
        observed = {item["item_id"] for item in _invalidations(snapshot)}
        supplied = [item["item_id"] for item in records]
        if len(supplied) != len(set(supplied)):
            blockers.append("curation:duplicate")
        if set(supplied) != observed:
            blockers.append("curation:not_bijective")
    return sorted(set(blockers))


@dataclass(frozen=True)
class ShadowPlan:
    body: Mapping[str, Any]
    plan_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "body", deep_freeze(self.body))

    def to_dict(self) -> dict[str, Any]:
        return {**deep_thaw(self.body), "plan_digest": self.plan_digest}


@dataclass(frozen=True)
class MigrationDiscovery:
    complete: bool
    blockers: tuple[str, ...]
    run_dir: str | None = None
    inventory_digest: str | None = None
    shadow_plan_digest: str | None = None
    plan: ShadowPlan | None = None


def _shadow_plan(
    snapshot: Mapping[str, Any],
    source_bank: BankRef,
    candidate_bank: BankRef,
    manifest: Mapping[str, Any],
    manifest_digest: str,
    inventory_digest: str,
    high_water: Sequence[Mapping[str, Any]],
    invalidations: Sequence[Mapping[str, Any]],
    private_catalog_digests: Mapping[str, str],
) -> ShadowPlan:
    coverage = _live_coverage(snapshot)
    curation = sorted((_normalized(item) for item in manifest["invalidation_dispositions"]), key=lambda item: item["item_id"])
    body = {
        "schema_version": 1,
        "kind": "migration-shadow-plan",
        "approved": False,
        "mutation_authority": "none",
        "complete": True,
        "blockers": [],
        "source_bank": source_bank.to_dict(),
        "candidate_bank": candidate_bank.to_dict(),
        "bindings": {
            "inventory_digest": inventory_digest,
            "offline_package_manifest_digest": manifest_digest,
            "offline_package_artifact_digest": manifest["artifact_digest"],
            "projection_digest": manifest["projection_digest"],
            "tag_mapping_digest": manifest["tag_mapping_digest"],
            "high_water_manifest_digest": digest(high_water),
            "invalidation_manifest_digest": digest(invalidations),
            "source_coverage_digest": digest(coverage["source"]),
            "candidate_coverage_digest": digest(coverage["candidate"]),
            "invalidation_disposition_digest": digest(curation),
            "candidate_provenance_digest": manifest["candidate_provenance_digest"],
            "candidate_curation_digest": manifest["candidate_curation_digest"],
            "private_catalog_digests": _normalized(private_catalog_digests),
            "endpoint_digest": digest(snapshot["endpoint"]),
            "provider_identity_digest": digest(snapshot["provider_identity"]),
            "versions_digest": digest(snapshot["versions"]),
        },
        "coverage": coverage,
        "invalidation_dispositions": curation,
        "semantic_diff": {
            "source_items": len(coverage["source"]),
            "candidate_items": len(coverage["candidate"]),
            "proposed_retains": sum(item["disposition"] == "retain" for rows in coverage.values() for item in rows),
            "invalidations": len(curation),
            "reapplications": sum(item["disposition"] == "reapply" for item in curation),
        },
        "operations": {"idle": True, "active_operation_ids": []},
        "legacy_observations_imported": False,
        "rollback_requirements": ROLLBACK_REQUIREMENTS,
        "cutover": CUTOVER_REQUIREMENTS,
        "closeout": CLOSEOUT_REQUIREMENTS,
        "archive_retirement": ARCHIVE_RETIREMENT_REQUIREMENTS,
    }
    return ShadowPlan(body, digest(body))


def verify_shadow_plan(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != PLAN_KEYS:
        raise MigrationError("shadow plan keys are closed")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "migration-shadow-plan":
        raise MigrationError("shadow plan schema is invalid")
    if value["approved"] is not False or value["mutation_authority"] != "none" or value["complete"] is not True:
        raise MigrationError("shadow plan cannot carry mutation authority")
    if value["blockers"] != [] or value["legacy_observations_imported"] is not False:
        raise MigrationError("shadow plan safety gates are invalid")
    for role in ("source_bank", "candidate_bank"):
        bank = value[role]
        if not isinstance(bank, Mapping) or set(bank) != {"profile_id", "bank_id"}:
            raise MigrationError("shadow plan bank reference is invalid")
        _identifier(bank["profile_id"], "bank profile ID")
        _identifier(bank["bank_id"], "bank ID")
    if value["source_bank"] == value["candidate_bank"]:
        raise MigrationError("shadow plan banks must be distinct")
    bindings = value["bindings"]
    if not isinstance(bindings, Mapping) or set(bindings) != BINDING_KEYS:
        raise MigrationError("shadow plan bindings are closed")
    for key in BINDING_KEYS - {"private_catalog_digests"}:
        _sha(bindings[key], f"shadow plan {key}")
    catalogs = bindings["private_catalog_digests"]
    if not isinstance(catalogs, Mapping) or not catalogs:
        raise MigrationError("shadow plan private catalog digests are invalid")
    for key, item in catalogs.items():
        _identifier(key, "private catalog digest name")
        _sha(item, "private catalog digest")
    coverage = value["coverage"]
    if not isinstance(coverage, Mapping) or set(coverage) != {"source", "candidate"}:
        raise MigrationError("shadow plan coverage is closed")
    for role in ("source", "candidate"):
        if not isinstance(coverage[role], list):
            raise MigrationError("shadow plan coverage is invalid")
        identifiers: list[str] = []
        for item in coverage[role]:
            if not isinstance(item, Mapping) or set(item) != COVERAGE_KEYS:
                raise MigrationError("shadow plan coverage record is invalid")
            identifiers.append(_identifier(item["item_id"], "coverage item ID"))
            _sha(item["content_digest"], "coverage content digest")
            _identifier(item["reason"], "coverage reason")
            if item["disposition"] not in {"retain", "omit", "duplicate", "supersede"}:
                raise MigrationError("shadow plan coverage disposition is invalid")
            if item["disposition"] == "retain":
                if not isinstance(item["semantic_scope"], str) or SEMANTIC_SCOPE.fullmatch(item["semantic_scope"]) is None:
                    raise MigrationError("shadow plan semantic scope is invalid")
            elif item["semantic_scope"] is not None:
                raise MigrationError("shadow plan semantic scope is invalid")
        if len(identifiers) != len(set(identifiers)):
            raise MigrationError("shadow plan coverage contains duplicates")
        if identifiers != sorted(identifiers):
            raise MigrationError("shadow plan coverage must be canonically ordered")
        if not hmac.compare_digest(digest(coverage[role]), bindings[f"{role}_coverage_digest"]):
            raise MigrationError("shadow plan coverage digest does not match")
    curation = value["invalidation_dispositions"]
    if not isinstance(curation, list):
        raise MigrationError("shadow plan invalidation dispositions are invalid")
    invalidation_ids: list[str] = []
    for item in curation:
        if not isinstance(item, Mapping) or set(item) != INVALIDATION_KEYS:
            raise MigrationError("shadow plan invalidation disposition is invalid")
        invalidation_ids.append(_identifier(item["item_id"], "invalidation item ID"))
        _identifier(item["reason"], "invalidation reason")
        if item["disposition"] not in {"exclude", "supersede", "reapply"}:
            raise MigrationError("shadow plan invalidation disposition is invalid")
        if item["disposition"] == "reapply":
            _sha(item["reapply_content_digest"], "reapply content digest")
        elif item["reapply_content_digest"] is not None:
            raise MigrationError("shadow plan invalidation disposition is invalid")
    if len(invalidation_ids) != len(set(invalidation_ids)):
        raise MigrationError("shadow plan invalidation dispositions contain duplicates")
    if invalidation_ids != sorted(invalidation_ids):
        raise MigrationError("shadow plan invalidation dispositions must be canonically ordered")
    if not hmac.compare_digest(digest(curation), bindings["invalidation_disposition_digest"]):
        raise MigrationError("shadow plan invalidation disposition digest does not match")
    semantic = value["semantic_diff"]
    expected_semantic = {
        "source_items": len(coverage["source"]),
        "candidate_items": len(coverage["candidate"]),
        "proposed_retains": sum(item["disposition"] == "retain" for rows in coverage.values() for item in rows),
        "invalidations": len(curation),
        "reapplications": sum(item["disposition"] == "reapply" for item in curation),
    }
    if canonical_bytes(semantic) != canonical_bytes(expected_semantic):
        raise MigrationError("shadow plan semantic diff is invalid")
    if canonical_bytes(value["operations"]) != canonical_bytes({"idle": True, "active_operation_ids": []}):
        raise MigrationError("shadow plan operations must be idle")
    if canonical_bytes(value["rollback_requirements"]) != canonical_bytes(ROLLBACK_REQUIREMENTS):
        raise MigrationError("shadow plan rollback requirements are invalid")
    if canonical_bytes(value["cutover"]) != canonical_bytes(CUTOVER_REQUIREMENTS):
        raise MigrationError("shadow plan cutover requirements are invalid")
    if canonical_bytes(value["closeout"]) != canonical_bytes(CLOSEOUT_REQUIREMENTS):
        raise MigrationError("shadow plan closeout requirements are invalid")
    if canonical_bytes(value["archive_retirement"]) != canonical_bytes(ARCHIVE_RETIREMENT_REQUIREMENTS):
        raise MigrationError("shadow plan archive retirement requirements are invalid")
    _sha(value["plan_digest"], "shadow plan digest")
    body = {key: deep_thaw(item) for key, item in value.items() if key != "plan_digest"}
    if not hmac.compare_digest(digest(body), value["plan_digest"]):
        raise MigrationError("shadow plan digest does not match its body")


def _validate_private_directory(metadata: os.stat_result) -> None:
    if not stat.S_ISDIR(metadata.st_mode):
        raise MigrationError("migration artifact path must be a directory")
    if metadata.st_uid != os.geteuid():
        raise MigrationError(
            "migration artifact directory must be owned by the current user"
        )
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise MigrationError("migration artifact directory must have mode 0700")


def _reject_git_worktree_descriptor(descriptor: int) -> None:
    try:
        os.stat(".git", dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        raise MigrationError(
            "migration artifact Git-worktree boundary is unavailable"
        ) from None
    raise MigrationError(
        "migration artifact directory must be outside a Git worktree"
    )


DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _verify_directory_entry(
    parent_descriptor: int,
    name: str,
    descriptor: int,
    label: str,
) -> None:
    try:
        entry = os.stat(
            name, dir_fd=parent_descriptor, follow_symlinks=False
        )
        opened = os.fstat(descriptor)
    except OSError:
        raise MigrationError(f"{label} identity changed") from None
    if (
        not stat.S_ISDIR(entry.st_mode)
        or (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        raise MigrationError(f"{label} identity changed")


@contextmanager
def _directory_chain(path: Path):
    """Open every absolute-path component without following symlinks."""
    if not path.is_absolute():
        raise MigrationError("migration artifact directory must be absolute")
    descriptors: list[int] = []
    links: list[tuple[int, str, int]] = []
    try:
        descriptors.append(os.open(path.anchor, DIRECTORY_FLAGS))
        _reject_git_worktree_descriptor(descriptors[-1])
        for component in path.parts[1:]:
            parent_descriptor = descriptors[-1]
            descriptor = os.open(
                component, DIRECTORY_FLAGS, dir_fd=parent_descriptor
            )
            descriptors.append(descriptor)
            _verify_directory_entry(
                parent_descriptor,
                component,
                descriptor,
                "migration artifact directory ancestor",
            )
            _reject_git_worktree_descriptor(descriptor)
            links.append((parent_descriptor, component, descriptor))
    except OSError:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise MigrationError("migration artifact directory is unavailable") from None
    except MigrationError:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise
    try:
        yield descriptors[-1]
        for descriptor in descriptors:
            _reject_git_worktree_descriptor(descriptor)
        for parent_descriptor, component, descriptor in links:
            _verify_directory_entry(
                parent_descriptor,
                component,
                descriptor,
                "migration artifact directory ancestor",
            )
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


@contextmanager
def _private_directory(path: Path):
    if not path.is_absolute():
        raise MigrationError("migration artifact directory must be absolute")
    _reject_symlink_components(path, "migration artifact directory")
    try:
        canonical = Path(os.path.abspath(os.fspath(path)))
        if len(canonical.parts) > 1:
            top_level = Path(canonical.anchor) / canonical.parts[1]
            if top_level.is_symlink():
                canonical = top_level.resolve(strict=True).joinpath(
                    *canonical.parts[2:]
                )
    except (OSError, RuntimeError):
        raise MigrationError("migration artifact directory is unavailable") from None
    with _directory_chain(canonical.parent) as parent_descriptor:
        directory_name = canonical.name
        created = False
        try:
            descriptor = os.open(
                directory_name, DIRECTORY_FLAGS, dir_fd=parent_descriptor
            )
        except FileNotFoundError:
            try:
                os.mkdir(directory_name, 0o700, dir_fd=parent_descriptor)
                created = True
                os.fsync(parent_descriptor)
                descriptor = os.open(
                    directory_name, DIRECTORY_FLAGS, dir_fd=parent_descriptor
                )
            except OSError:
                if created:
                    try:
                        os.rmdir(directory_name, dir_fd=parent_descriptor)
                        os.fsync(parent_descriptor)
                    except OSError:
                        pass
                raise MigrationError(
                    "migration artifact directory is unavailable"
                ) from None
        except OSError:
            raise MigrationError(
                "migration artifact directory is unavailable"
            ) from None
        try:
            _verify_directory_entry(
                parent_descriptor,
                directory_name,
                descriptor,
                "migration artifact directory",
            )
            _reject_git_worktree_descriptor(descriptor)
            _validate_private_directory(os.fstat(descriptor))
            yield canonical, descriptor
            _verify_directory_entry(
                parent_descriptor,
                directory_name,
                descriptor,
                "migration artifact directory",
            )
            _reject_git_worktree_descriptor(descriptor)
            _validate_private_directory(os.fstat(descriptor))
        finally:
            os.close(descriptor)


def _write_exclusive(
    directory_descriptor: int, name: str, value: Any
) -> tuple[int, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(
        name, flags, 0o600, dir_fd=directory_descriptor
    )
    identity = os.fstat(descriptor)
    published = False

    def entry_is_owned() -> bool:
        try:
            entry = os.stat(
                name, dir_fd=directory_descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            return False
        return (
            stat.S_ISREG(entry.st_mode)
            and (entry.st_dev, entry.st_ino) == (identity.st_dev, identity.st_ino)
        )

    try:
        data = canonical_bytes(value) + b"\n"
        written = 0
        while written < len(data):
            count = os.write(descriptor, data[written:])
            if count <= 0:
                raise OSError("migration artifact write made no progress")
            written += count
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (metadata.st_dev, metadata.st_ino)
            != (identity.st_dev, identity.st_ino)
        ):
            raise MigrationError("migration artifact file is not private")
        if not entry_is_owned():
            raise MigrationError("migration artifact file identity changed")
        os.fsync(directory_descriptor)
        if not entry_is_owned():
            raise MigrationError("migration artifact file identity changed")
        published = True
    except BaseException:
        if entry_is_owned():
            try:
                os.unlink(name, dir_fd=directory_descriptor)
                os.fsync(directory_descriptor)
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(descriptor)
    if not published:
        raise MigrationError("migration artifact file was not published")
    return identity.st_dev, identity.st_ino


def _rename_directory_no_replace(
    directory_descriptor: int, source: str, destination: str
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        result = library.renameatx_np(
            directory_descriptor,
            source_bytes,
            directory_descriptor,
            destination_bytes,
            0x00000004,  # RENAME_EXCL
        )
    elif hasattr(library, "renameat2"):
        result = library.renameat2(
            directory_descriptor,
            source_bytes,
            directory_descriptor,
            destination_bytes,
            0x00000001,  # RENAME_NOREPLACE
        )
    else:
        raise MigrationError("atomic no-replace publication is unavailable")
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise MigrationError("migration discovery run already exists")
        raise MigrationError("migration discovery run publication failed")


def _write_artifacts(root: Path, timestamp: str, inventory: Mapping[str, Any], plan: ShadowPlan) -> Path:
    run_name = f"controller-discovery-{timestamp}"
    staging_name = f".{run_name}.{secrets.token_hex(8)}.tmp"
    with _private_directory(root) as (canonical_root, root_descriptor):
        try:
            os.mkdir(staging_name, 0o700, dir_fd=root_descriptor)
            os.fsync(root_descriptor)
        except OSError as error:
            raise MigrationError(
                "migration discovery staging directory is unavailable"
            ) from error
        try:
            run_descriptor = os.open(
                staging_name, DIRECTORY_FLAGS, dir_fd=root_descriptor
            )
        except BaseException:
            os.rmdir(staging_name, dir_fd=root_descriptor)
            os.fsync(root_descriptor)
            raise
        written: list[tuple[str, tuple[int, int]]] = []
        published = False
        try:
            _verify_directory_entry(
                root_descriptor,
                staging_name,
                run_descriptor,
                "migration discovery staging directory",
            )
            _validate_private_directory(os.fstat(run_descriptor))
            for name, value in (
                ("inventory.json", inventory),
                ("shadow-plan.json", plan.to_dict()),
            ):
                identity = _write_exclusive(run_descriptor, name, value)
                written.append((name, identity))
            os.fsync(run_descriptor)
            _rename_directory_no_replace(
                root_descriptor, staging_name, run_name
            )
            published = True
            os.fsync(root_descriptor)
            _verify_directory_entry(
                root_descriptor,
                run_name,
                run_descriptor,
                "migration discovery run directory",
            )
            _validate_private_directory(os.fstat(run_descriptor))
        except BaseException:
            for name, identity in reversed(written):
                try:
                    entry = os.stat(
                        name, dir_fd=run_descriptor, follow_symlinks=False
                    )
                    if (entry.st_dev, entry.st_ino) == identity:
                        os.unlink(name, dir_fd=run_descriptor)
                except (FileNotFoundError, OSError):
                    pass
            run_entry_is_current = True
            current_name = run_name if published else staging_name
            try:
                _verify_directory_entry(
                    root_descriptor,
                    current_name,
                    run_descriptor,
                    "migration discovery run directory",
                )
            except MigrationError:
                run_entry_is_current = False
            os.close(run_descriptor)
            if run_entry_is_current:
                try:
                    os.rmdir(current_name, dir_fd=root_descriptor)
                except OSError:
                    pass
                else:
                    os.fsync(root_descriptor)
            raise
        else:
            os.close(run_descriptor)
        return canonical_root / run_name


def discover_migration_state(
    adapter: Any,
    *,
    source_bank: BankRef,
    candidate_bank: BankRef,
    offline_package_manifest: Mapping[str, Any],
    approved_offline_package_digest: str,
    migration_paths: Mapping[str, Any],
    retain_watermark_reader: Callable[[], Mapping[str, Any]],
    private_catalog_digests: Mapping[str, str],
    timestamp: str,
) -> MigrationDiscovery:
    if not isinstance(source_bank, BankRef) or not isinstance(candidate_bank, BankRef) or source_bank == candidate_bank:
        raise MigrationError("source and candidate bank references must be explicit and distinct")
    if not isinstance(timestamp, str) or TIMESTAMP.fullmatch(timestamp) is None:
        raise MigrationError("timestamp must use YYYYmmddTHHMMSSZ")
    if not isinstance(private_catalog_digests, Mapping) or not private_catalog_digests:
        raise MigrationError("private catalog digests are required")
    for key, value in private_catalog_digests.items():
        _identifier(key, "private catalog digest name")
        _sha(value, "private catalog digest")

    try:
        before_generation = _adapter_generation_snapshot(adapter)
    except MigrationError:
        return MigrationDiscovery(
            False, ("adapter:migration_generation_unavailable",)
        )
    before_gate = _gate_snapshot(migration_paths)
    before_watermarks = _retain_watermark_snapshot(retain_watermark_reader)
    package_blockers = _package_blockers(offline_package_manifest, approved_offline_package_digest)
    try:
        before = _with_retain_watermarks(
            adapter.read_migration_inventory(source_bank, candidate_bank),
            before_watermarks,
        )
        after = _with_retain_watermarks(
            adapter.read_migration_inventory(source_bank, candidate_bank),
            _retain_watermark_snapshot(retain_watermark_reader),
        )
    except AdapterError:
        return MigrationDiscovery(False, ("adapter:migration_inventory_unavailable",))
    after_gate = _gate_snapshot(migration_paths)
    try:
        after_generation = _adapter_generation_snapshot(adapter)
    except MigrationError:
        return MigrationDiscovery(
            False, ("adapter:migration_generation_unavailable",)
        )

    blockers = _snapshot_blockers(before, source_bank, candidate_bank)
    blockers.extend(_snapshot_blockers(after, source_bank, candidate_bank))
    blockers.extend(package_blockers)
    if not blockers:
        if not hmac.compare_digest(
            before_generation.encode("utf-8"), after_generation.encode("utf-8")
        ):
            blockers.append("drift:adapter_generation")
        blockers.extend(_drift_blockers(before, after, before_gate, after_gate))
        blockers.extend(_coverage_blockers(before, offline_package_manifest))
    blockers = sorted(set(blockers))
    if blockers:
        return MigrationDiscovery(False, tuple(blockers))

    normalized_snapshot = _normalized(before)
    high_water = _high_water(normalized_snapshot)
    invalidations = _invalidations(normalized_snapshot)
    inventory = {
        "schema_version": 1,
        "adapter_generation": before_generation,
        "snapshot": normalized_snapshot,
        "high_water_manifest": high_water,
        "invalidation_manifest": invalidations,
        "completion_gate_snapshot": before_gate,
    }
    inventory_digest = digest(inventory)
    manifest_digest = _offline_package_digest(offline_package_manifest)
    plan = _shadow_plan(
        normalized_snapshot,
        source_bank,
        candidate_bank,
        _normalized(offline_package_manifest),
        manifest_digest,
        inventory_digest,
        high_water,
        invalidations,
        private_catalog_digests,
    )
    verify_shadow_plan(plan.to_dict())
    artifact_root = Path(str(migration_paths["artifact_dir"])).expanduser()
    run_dir = _write_artifacts(artifact_root, timestamp, inventory, plan)
    return MigrationDiscovery(True, (), str(run_dir), inventory_digest, plan.plan_digest, plan)
