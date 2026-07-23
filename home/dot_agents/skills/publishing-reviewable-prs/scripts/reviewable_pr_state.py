"""Shared exact-state operations for guarded PR publication."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any


REPOSITORY_RE = re.compile(r"[^/\s]+/[^/\s]+")
OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
PR_URL_RE = re.compile(
    r"https://github\.com/(?P<repository>[^/]+/[^/]+)/pull/(?P<pr>\d+)"
)
STORED_FIELDS = (
    "number,url,title,body,baseRefName,baseRefOid,headRefName,"
    "headRefOid,headRepositoryOwner,isDraft,state"
)


class PublicationError(RuntimeError):
    """A PR publication operation could not reach a verified result."""


class StateReadError(PublicationError):
    """The current PR state could not be established."""


@dataclass(frozen=True)
class ExpectedIdentity:
    repository: str
    pr_number: int
    base: str
    base_oid: str
    head: str
    head_oid: str
    head_owner: str

    @property
    def head_branch(self) -> str:
        return self.head.split(":", 1)[1]

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repository}/pull/{self.pr_number}"


def run(
    arguments: list[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise PublicationError(f"{arguments[0]} failed: {detail}")
    return result


def _json_object(output: str, source: str) -> dict[str, Any]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as error:
        raise StateReadError(f"{source} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise StateReadError(f"{source} returned an unexpected value")
    return value


def stored_pr(repository: str, pr_number: int) -> dict[str, Any]:
    try:
        result = run(
            [
                "gh",
                "-R",
                repository,
                "pr",
                "view",
                str(pr_number),
                "--json",
                STORED_FIELDS,
            ]
        )
    except PublicationError as error:
        raise StateReadError(f"cannot read PR state: {error}") from error
    return _json_object(result.stdout, "gh pr view")


def open_prs(repository: str, base: str, head: str) -> list[dict[str, Any]]:
    head_branch = head.split(":", 1)[1]
    try:
        result = run(
            [
                "gh",
                "-R",
                repository,
                "pr",
                "list",
                "--state",
                "open",
                "--base",
                base,
                "--head",
                head_branch,
                "--json",
                STORED_FIELDS,
            ]
        )
    except PublicationError as error:
        raise StateReadError(f"cannot list matching PRs: {error}") from error
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise StateReadError("gh pr list returned invalid JSON") from error
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise StateReadError("gh pr list returned an unexpected value")
    return value


def validate_identity_inputs(
    *,
    repository: str,
    pr_number: int | None,
    base: str,
    base_oid: str,
    head: str,
    head_oid: str,
    head_owner: str,
) -> None:
    if REPOSITORY_RE.fullmatch(repository) is None:
        raise PublicationError("repository must use OWNER/REPO")
    if pr_number is not None and pr_number <= 0:
        raise PublicationError("PR number must be positive")
    if not base.strip():
        raise PublicationError("base must be non-empty")
    if ":" not in head or not all(part.strip() for part in head.split(":", 1)):
        raise PublicationError("head must use OWNER:BRANCH")
    if head.split(":", 1)[0] != head_owner:
        raise PublicationError("head owner must exactly match the OWNER in head")
    if OID_RE.fullmatch(base_oid) is None:
        raise PublicationError("base OID must be a lowercase 40- or 64-digit hex OID")
    if OID_RE.fullmatch(head_oid) is None:
        raise PublicationError("head OID must be a lowercase 40- or 64-digit hex OID")


def head_base_matches(
    stored: dict[str, Any],
    *,
    base: str,
    head: str,
    head_owner: str,
) -> bool:
    owner = stored.get("headRepositoryOwner")
    stored_owner = owner.get("login") if isinstance(owner, dict) else None
    return (
        stored.get("baseRefName") == base
        and stored.get("headRefName") == head.split(":", 1)[1]
        and stored_owner == head_owner
        and stored.get("state") == "OPEN"
    )


def identity_matches(stored: dict[str, Any], expected: ExpectedIdentity) -> bool:
    return (
        stored.get("number") == expected.pr_number
        and stored.get("url") == expected.url
        and head_base_matches(
            stored,
            base=expected.base,
            head=expected.head,
            head_owner=expected.head_owner,
        )
        and stored.get("baseRefOid") == expected.base_oid
        and stored.get("headRefOid") == expected.head_oid
    )


def state_matches(
    stored: dict[str, Any],
    expected: ExpectedIdentity,
    *,
    title: str,
    body: str,
    is_draft: bool,
) -> bool:
    return (
        identity_matches(stored, expected)
        and stored.get("title") == title
        and stored.get("body") == body
        and stored.get("isDraft") is is_draft
    )
