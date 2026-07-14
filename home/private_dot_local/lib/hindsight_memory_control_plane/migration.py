"""Read-only migration discovery and immutable, unapproved shadow planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hmac
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping, Sequence

from .adapters import AdapterError
from .canonical import canonical_bytes, digest
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
    "artifact_digest",
    "projection_digest",
    "tag_mapping_digest",
    "candidate_provenance_digest",
    "candidate_curation_digest",
    "source_coverage",
    "candidate_coverage",
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


def _read_gate(path: str, label: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise MigrationError(f"{label} path must be absolute")
    _reject_symlink_components(target, label)
    if not target.exists():
        return {"exists": False, "digest": None}
    if not target.is_file():
        raise MigrationError(f"{label} path must be a regular file")
    return {"exists": True, "digest": hashlib.sha256(target.read_bytes()).hexdigest()}


def _reject_symlink_components(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) and not (
            current.parent == Path("/") and metadata.st_uid == 0
        ):
            raise MigrationError(f"{label} path must not contain symlinks")


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
    if snapshot["schema_version"] != 1:
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
    if manifest["schema_version"] != 1:
        blockers.append("offline_package:invalid_schema")
    for key in (
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
    if not isinstance(approved_digest, str) or DIGEST.fullmatch(approved_digest) is None or not hmac.compare_digest(digest(_normalized(manifest)), approved_digest):
        blockers.append("offline_package:digest_mismatch")
    for key in ("source_coverage", "candidate_coverage", "invalidation_dispositions"):
        if not isinstance(manifest[key], list):
            blockers.append(f"offline_package:invalid_{key}")
    return sorted(set(blockers))


def _coverage_blockers(snapshot: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for role in ("source", "candidate"):
        raw = manifest[f"{role}_coverage"]
        if not isinstance(raw, list):
            continue
        records = []
        for item in raw:
            if not isinstance(item, Mapping) or set(item) != COVERAGE_KEYS:
                blockers.append(f"coverage:{role}:invalid_record")
                continue
            records.append(item)
            try:
                _identifier(item["item_id"], "coverage item ID")
                _sha(item["content_digest"], "coverage content digest")
                _identifier(item["reason"], "coverage reason")
            except MigrationError:
                blockers.append(f"coverage:{role}:invalid_record")
            if item["disposition"] not in {"retain", "omit", "duplicate", "supersede"}:
                blockers.append(f"coverage:{role}:invalid_disposition")
            if item["disposition"] == "retain":
                if not isinstance(item["semantic_scope"], str) or SEMANTIC_SCOPE.fullmatch(item["semantic_scope"]) is None:
                    blockers.append(f"coverage:{role}:invalid_semantic_scope")
            elif item["semantic_scope"] is not None:
                blockers.append(f"coverage:{role}:unexpected_semantic_scope")
        observed = {item["document_id"]: item["content_digest"] for item in snapshot["banks"][role]["documents"]}
        supplied = [item["item_id"] for item in records]
        if len(supplied) != len(set(supplied)):
            blockers.append(f"coverage:{role}:duplicate")
        if set(supplied) != set(observed):
            blockers.append(f"coverage:{role}:not_bijective")
        for item in records:
            if observed.get(item["item_id"]) != item["content_digest"]:
                blockers.append(f"coverage:{role}:digest_mismatch")
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
    coverage = {
        role: sorted((_normalized(item) for item in manifest[f"{role}_coverage"]), key=lambda item: item["item_id"])
        for role in ("source", "candidate")
    }
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


def _private_directory(path: Path) -> None:
    if not path.is_absolute():
        raise MigrationError("migration artifact directory must be absolute")
    _reject_symlink_components(path, "migration artifact directory")
    if path.exists():
        if not path.is_dir():
            raise MigrationError("migration artifact path must be a directory")
        if stat.S_IMODE(path.stat().st_mode) != 0o700:
            raise MigrationError("migration artifact directory must have mode 0700")
        return
    if not path.parent.is_dir():
        raise MigrationError("migration artifact directory parent must already exist")
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)


def _write_exclusive(path: Path, value: Any) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        data = canonical_bytes(value) + b"\n"
        written = 0
        while written < len(data):
            written += os.write(descriptor, data[written:])
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    else:
        os.close(descriptor)


def _write_artifacts(root: Path, timestamp: str, inventory: Mapping[str, Any], plan: ShadowPlan) -> Path:
    _private_directory(root)
    run_dir = root / f"controller-discovery-{timestamp}"
    try:
        os.mkdir(run_dir, 0o700)
    except FileExistsError as error:
        raise MigrationError("migration discovery run already exists") from error
    os.chmod(run_dir, 0o700)
    written: list[Path] = []
    try:
        for name, value in (("inventory.json", inventory), ("shadow-plan.json", plan.to_dict())):
            target = run_dir / name
            written.append(target)
            _write_exclusive(target, value)
    except Exception:
        for target in reversed(written):
            target.unlink(missing_ok=True)
        run_dir.rmdir()
        raise
    return run_dir


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

    blockers = _snapshot_blockers(before, source_bank, candidate_bank)
    blockers.extend(_snapshot_blockers(after, source_bank, candidate_bank))
    blockers.extend(package_blockers)
    if not blockers:
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
        "snapshot": normalized_snapshot,
        "high_water_manifest": high_water,
        "invalidation_manifest": invalidations,
        "completion_gate_snapshot": before_gate,
    }
    inventory_digest = digest(inventory)
    manifest_digest = digest(_normalized(offline_package_manifest))
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
