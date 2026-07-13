"""Deterministic, approval-gated projections for external memory sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hmac
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from .canonical import digest
from .model import deep_freeze, deep_thaw


class ImportError(ValueError):
    pass


SOURCE_TAGS = {
    "codex": "source:codex-memory-archive",
    "claude": "source:file-memory",
    "portable-markdown": "source:portable-import",
    "portable-jsonl": "source:portable-import",
}
COVERAGE_DISPOSITIONS = frozenset(
    {"proposed_novel", "proposed_duplicate", "proposed_conflict", "omitted"}
)
KINDS = frozenset(
    {
        "rule", "principle", "runbook", "decision", "incident", "state",
        "reference", "preference", "goal", "commitment", "relationship",
        "routine", "logistics", "project",
    }
)
RECORD_KEYS = {
    "source_locator", "source_native_id", "timestamp", "line_start", "line_end",
    "content", "kind", "intended_scope", "relationships",
    "coverage_disposition", "coverage_reason",
}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}\Z")
SCOPE = re.compile(r"(?:global|personal|repo:[a-z0-9][a-z0-9._-]*|workflow:[a-z0-9][a-z0-9._-]*)\Z")
RELATIONSHIP = re.compile(r"(?:repo|workflow|item|person):[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SECRET = re.compile(
    r"(?:-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|"
    r"\b(?:password|passwd|api[_-]?key|access[_-]?token|secret)\s*[:=]|"
    r"\b(?:gh[opusr]_|sk-)[A-Za-z0-9_-]{6,})",
    re.IGNORECASE,
)
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ImportError(f"{label} must be a bounded identifier")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ImportError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _timestamp(value: Any) -> str:
    if not isinstance(value, str):
        raise ImportError("timestamp must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ImportError("timestamp must be ISO-8601 with timezone") from exc
    if parsed.tzinfo is None:
        raise ImportError("timestamp must include a timezone")
    return value


@dataclass(frozen=True)
class ImportItem:
    item_id: str
    source_kind: str
    source_native_id: str
    timestamp: str
    provenance: Mapping[str, Any]
    content: str
    content_digest: str
    tags: tuple[str, ...]
    intended_scope: str
    relationships: tuple[str, ...]
    coverage_disposition: str
    coverage_reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", deep_freeze(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "source_kind": self.source_kind,
            "source_native_id": self.source_native_id,
            "timestamp": self.timestamp,
            "provenance": deep_thaw(self.provenance),
            "content": self.content,
            "content_digest": self.content_digest,
            "tags": list(self.tags),
            "intended_scope": self.intended_scope,
            "relationships": list(self.relationships),
            "coverage": {
                "disposition": self.coverage_disposition,
                "reason": self.coverage_reason,
            },
        }


@dataclass(frozen=True)
class ImportProjection:
    schema_version: int
    items: tuple[ImportItem, ...]
    pending_items: tuple[ImportItem, ...]
    skipped_item_ids: tuple[str, ...]
    projection_digest: str

    def body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "items": [item.to_dict() for item in self.items],
            "pending_item_ids": [item.item_id for item in self.pending_items],
            "skipped_item_ids": list(self.skipped_item_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "projection_digest": self.projection_digest}


@dataclass(frozen=True)
class ImportPlan:
    schema_version: int
    projection_digest: str
    coverage_digest: str
    controller_plan_digest: str
    actions: tuple[Mapping[str, str], ...]
    plan_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", tuple(deep_freeze(value) for value in self.actions))

    def body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "projection_digest": self.projection_digest,
            "coverage_digest": self.coverage_digest,
            "controller_plan_digest": self.controller_plan_digest,
            "actions": [deep_thaw(value) for value in self.actions],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "plan_digest": self.plan_digest}


@dataclass(frozen=True)
class ReconcileResult:
    complete: bool
    imported_item_ids: tuple[str, ...]
    missing_item_ids: tuple[str, ...]
    reconciliation_digest: str


def inspect_items(source_kind: str, records: Sequence[Mapping[str, Any]]) -> tuple[ImportItem, ...]:
    if source_kind not in SOURCE_TAGS:
        raise ImportError("source kind is not supported")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ImportError("source records must be an array")
    result: list[ImportItem] = []
    identities: set[str] = set()
    for raw in records:
        if not isinstance(raw, dict) or set(raw) != RECORD_KEYS:
            raise ImportError("source record keys are closed")
        locator = _identifier(raw["source_locator"], "source locator")
        native_id = _identifier(raw["source_native_id"], "source native identity")
        item_id = digest({"source_locator": locator, "source_native_id": native_id})
        if item_id in identities:
            raise ImportError("duplicate source identity")
        identities.add(item_id)
        line_start, line_end = raw["line_start"], raw["line_end"]
        if type(line_start) is not int or type(line_end) is not int or line_start < 1 or line_end < line_start:
            raise ImportError("provenance lines must be a positive ordered range")
        content = raw["content"]
        if not isinstance(content, str) or not content.strip() or len(content.encode()) > 65536:
            raise ImportError("content must be non-empty and bounded")
        if SECRET.search(content):
            raise ImportError("secret-like content is not importable")
        kind = raw["kind"]
        if kind not in KINDS:
            raise ImportError("kind is not in the closed durable vocabulary")
        intended_scope = raw["intended_scope"]
        if not isinstance(intended_scope, str) or not SCOPE.fullmatch(intended_scope):
            raise ImportError("intended scope is not supported")
        relationships = raw["relationships"]
        if not isinstance(relationships, list) or any(not isinstance(value, str) or not RELATIONSHIP.fullmatch(value) for value in relationships):
            raise ImportError("relationships must use the closed hint vocabulary")
        if len(set(relationships)) != len(relationships):
            raise ImportError("relationships must be unique")
        disposition = raw["coverage_disposition"]
        if not isinstance(disposition, str) or disposition not in COVERAGE_DISPOSITIONS:
            raise ImportError("coverage disposition is not supported")
        reason = _identifier(raw["coverage_reason"], "coverage reason")
        tags = {SOURCE_TAGS[source_kind], f"kind:{kind}", "scope:active"}
        if intended_scope.startswith(("repo:", "workflow:")):
            tags.add(intended_scope)
        result.append(
            ImportItem(
                item_id=item_id,
                source_kind=source_kind,
                source_native_id=native_id,
                timestamp=_timestamp(raw["timestamp"]),
                provenance={"source_locator": locator, "line_start": line_start, "line_end": line_end},
                content=content,
                content_digest=digest(content),
                tags=tuple(sorted(tags)),
                intended_scope=intended_scope,
                relationships=tuple(sorted(relationships)),
                coverage_disposition=disposition,
                coverage_reason=reason,
            )
        )
    return tuple(sorted(result, key=lambda item: item.item_id))


def project_import(items: Iterable[ImportItem], *, resume_state: Mapping[str, str] | None = None) -> ImportProjection:
    ordered = tuple(sorted(tuple(items), key=lambda item: item.item_id))
    if len({item.item_id for item in ordered}) != len(ordered):
        raise ImportError("projection item identities must be unique")
    resume = dict(resume_state or {})
    for item_id, item_digest in resume.items():
        _sha(item_id, "resume item identity")
        _sha(item_digest, "resume item digest")
    skipped = tuple(item.item_id for item in ordered if resume.get(item.item_id) == item.content_digest)
    pending = tuple(item for item in ordered if item.item_id not in skipped)
    body = {
        "schema_version": 1,
        "items": [item.to_dict() for item in ordered],
        "pending_item_ids": [item.item_id for item in pending],
        "skipped_item_ids": list(skipped),
    }
    projection = ImportProjection(1, ordered, pending, skipped, digest(body))
    validate_projection(projection)
    return projection


def validate_projection(projection: ImportProjection) -> None:
    if projection.schema_version != 1:
        raise ImportError("projection schema_version must be integer 1")
    _sha(projection.projection_digest, "projection digest")
    if not hmac.compare_digest(digest(projection.body()), projection.projection_digest):
        raise ImportError("projection digest does not match projection body")


def build_import_plan(projection: ImportProjection, *, controller_plan_digest: str) -> ImportPlan:
    validate_projection(projection)
    _sha(controller_plan_digest, "controller plan digest")
    coverage = [
        {"item_id": item.item_id, "disposition": item.coverage_disposition, "reason": item.coverage_reason}
        for item in projection.items
    ]
    actions = tuple(
        {"item_id": item.item_id, "content_digest": item.content_digest, "operation": "retain"}
        for item in projection.pending_items
        if item.coverage_disposition != "omitted"
    )
    body = {
        "schema_version": 1,
        "projection_digest": projection.projection_digest,
        "coverage_digest": digest(coverage),
        "controller_plan_digest": controller_plan_digest,
        "actions": [dict(value) for value in actions],
    }
    return ImportPlan(1, projection.projection_digest, body["coverage_digest"], controller_plan_digest, actions, digest(body))


def apply_import_plan(
    plan: ImportPlan,
    *,
    approved_plan_digest: str | None,
    controller_apply: Callable[[dict[str, Any]], Any],
) -> str:
    if approved_plan_digest is None or not hmac.compare_digest(approved_plan_digest, plan.plan_digest):
        raise ImportError("exact digest-bound import plan approval is required")
    controller_apply(plan.to_dict())
    return plan.plan_digest


def reconcile_import(projection: ImportProjection, receipts: Sequence[Mapping[str, Any]]) -> ReconcileResult:
    validate_projection(projection)
    expected = {item.item_id: item.content_digest for item in projection.pending_items if item.coverage_disposition != "omitted"}
    seen: dict[str, str] = {}
    for raw in receipts:
        if not isinstance(raw, dict) or set(raw) != {"item_id", "content_digest", "status"}:
            raise ImportError("reconciliation receipt keys are closed")
        item_id = _sha(raw["item_id"], "receipt item identity")
        item_digest = _sha(raw["content_digest"], "receipt content digest")
        if raw["status"] != "imported" or item_id not in expected or expected[item_id] != item_digest or item_id in seen:
            raise ImportError("reconciliation receipt does not match the projection")
        seen[item_id] = item_digest
    imported = tuple(sorted(seen))
    missing = tuple(sorted(set(expected) - set(seen)))
    body = {"projection_digest": projection.projection_digest, "imported_item_ids": list(imported), "missing_item_ids": list(missing)}
    return ReconcileResult(not missing, imported, missing, digest(body))
