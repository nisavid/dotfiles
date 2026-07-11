"""Pure policy decisions for deterministic Git publication."""

from dataclasses import dataclass
from typing import Any, FrozenSet, Optional, Tuple


@dataclass(frozen=True)
class PublicationRequest:
    schema_version: int
    start_head: str
    source_sha: str
    task_owned_commits: FrozenSet[str]
    adopted_commits: FrozenSet[str]
    removal_authorized_commits: FrozenSet[str]
    explicit_destination: Optional[dict]
    allow_create: bool
    creation_base_ref: Optional[str]


@dataclass(frozen=True)
class RepositorySnapshot:
    remote: str
    ref: str
    endpoint_fingerprint: str
    config_digest: str
    target_present: bool
    target_sha: Optional[str]
    outgoing_shas: Tuple[str, ...]
    target_only_shas: Tuple[str, ...]
    target_is_ancestor: bool
    start_is_ancestor: bool
    start_advertised: bool
    creation_base_sha: Optional[str]
    creation_base_is_ancestor: Optional[bool]
    creation_base_to_start_shas: Tuple[str, ...]


def _reason(code: str, **evidence: Any) -> dict:
    return {"code": code, "evidence": evidence}


def _base_result(request: PublicationRequest, snapshot: RepositorySnapshot) -> dict:
    rewrite = bool(snapshot.target_present and snapshot.target_only_shas)
    return {
        "schema_version": 1,
        "status": "blocked",
        "reasons": [],
        "source_sha": request.source_sha,
        "destination": {
            "remote": snapshot.remote,
            "ref": snapshot.ref,
            "endpoint_fingerprint": snapshot.endpoint_fingerprint,
            "config_digest": snapshot.config_digest,
        },
        "target": {"present": snapshot.target_present, "sha": snapshot.target_sha},
        "outgoing_shas": list(snapshot.outgoing_shas),
        "target_only_shas": list(snapshot.target_only_shas),
        "fast_forward": bool(snapshot.target_present and snapshot.target_is_ancestor),
        "rewrite_required": rewrite,
        "push": None,
        "postchecks": [],
    }


def plan_publication(request: PublicationRequest, snapshot: RepositorySnapshot) -> dict:
    """Return a publication decision from a complete, normalized graph snapshot."""
    result = _base_result(request, snapshot)

    if snapshot.target_present and snapshot.target_sha == request.source_sha:
        result["status"] = "verified"
        result["postchecks"] = [
            {
                "kind": "remote_ref_equals",
                "endpoint_fingerprint": snapshot.endpoint_fingerprint,
                "ref": snapshot.ref,
                "sha": request.source_sha,
            }
        ]
        return result

    if not snapshot.start_is_ancestor:
        result["reasons"].append(_reason("START_NOT_ANCESTOR_OF_SOURCE", start_head=request.start_head))

    allowed = request.task_owned_commits | request.adopted_commits
    unowned = sorted(set(snapshot.outgoing_shas) - allowed)
    if unowned:
        result["reasons"].append(_reason("OUTGOING_COMMITS_NOT_OWNED_OR_ADOPTED", shas=unowned))

    if snapshot.target_present:
        unauthorized = sorted(set(snapshot.target_only_shas) - request.removal_authorized_commits)
        if unauthorized:
            result["status"] = "needs_reconciliation"
            result["reasons"].append(_reason("TARGET_ONLY_COMMITS_REQUIRE_REMOVAL_AUTHORIZATION", shas=unauthorized))
    else:
        if not request.allow_create:
            result["reasons"].append(_reason("TARGET_ABSENT_CREATION_NOT_ALLOWED", ref=snapshot.ref))
        if not snapshot.start_advertised:
            if request.creation_base_ref is None:
                result["reasons"].append(_reason("START_NOT_ADVERTISED_AT_DESTINATION", start_head=request.start_head))
            elif snapshot.creation_base_sha is None:
                result["reasons"].append(_reason("CREATION_BASE_REF_ABSENT", ref=request.creation_base_ref))
            elif not snapshot.creation_base_is_ancestor:
                result["reasons"].append(
                    _reason("CREATION_BASE_NOT_ANCESTOR_OF_START", ref=request.creation_base_ref)
                )
            else:
                unadopted = sorted(
                    set(snapshot.creation_base_to_start_shas) - request.adopted_commits
                )
                if unadopted:
                    result["reasons"].append(
                        _reason("CREATION_BASE_TO_START_COMMITS_NOT_ADOPTED", shas=unadopted)
                    )

    if result["reasons"]:
        if result["status"] != "needs_reconciliation" or len(result["reasons"]) > 1:
            result["status"] = "blocked"
        return result

    lease = (
        f"--force-with-lease={snapshot.ref}:{snapshot.target_sha}"
        if snapshot.target_present
        else f"--force-with-lease={snapshot.ref}:"
    )
    result["status"] = "ready"
    result["push"] = {
        "argv": [
            "git",
            "push",
            "--no-follow-tags",
            "--recurse-submodules=check",
            lease,
            "--",
            snapshot.remote,
            f"{request.source_sha}:{snapshot.ref}",
        ],
        "config_overrides": {
            "push.followTags": "false",
            "push.recurseSubmodules": "check",
        },
        "expected_target": {
            "present": snapshot.target_present,
            "sha": snapshot.target_sha,
        },
    }
    result["postchecks"] = [
        {
            "kind": "remote_ref_equals",
            "endpoint_fingerprint": snapshot.endpoint_fingerprint,
            "ref": snapshot.ref,
            "sha": request.source_sha,
        }
    ]
    return result
