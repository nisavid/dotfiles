#!/usr/bin/env python3
"""Bind a pull-request event to a fresh live GitHub API snapshot.

The event supplies only the repository and pull-request number. All values
used by the admission decision are reread from GitHub immediately before the
trusted verifier runs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

_SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if _SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, _SCRIPT_DIRECTORY)

try:
    from .privacy_age_admission_result import (
        AdmissionResultError,
        body_digest,
        canonical_json_bytes,
        make_snapshot,
        make_state,
    )
    from .privacy_age_envelopes import AgeEnvelopeError, read_regular_file
except ImportError:  # pragma: no cover - direct script execution
    from privacy_age_admission_result import (
        AdmissionResultError,
        body_digest,
        canonical_json_bytes,
        make_snapshot,
        make_state,
    )
    from privacy_age_envelopes import AgeEnvelopeError, read_regular_file

REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z", re.ASCII)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class SnapshotError(RuntimeError):
    """The live pull-request binding could not be established."""


class _RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise SnapshotError("GitHub API redirected a token-bearing request")


_OPENER = build_opener(_RejectRedirect())


def _api_root(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise SnapshotError("GitHub API endpoint is not an HTTPS origin")
    return value.rstrip("/")


def _request_json(*, api_root: str, path: str, token: str) -> object:
    if not token:
        raise SnapshotError("read token is unavailable")
    request = Request(
        f"{_api_root(api_root)}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with _OPENER.open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise SnapshotError("live pull-request response is oversized")
            return json.loads(raw.decode("utf-8"))
    except (
        HTTPError,
        URLError,
        OSError,
        TimeoutError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as error:
        raise SnapshotError("live pull-request API read failed") from error


def event_identity(event: object, *, expected_repository: str) -> tuple[str, int]:
    if REPOSITORY.fullmatch(expected_repository) is None:
        raise SnapshotError("expected repository identity is invalid")
    if not isinstance(event, dict):
        raise SnapshotError("pull-request event is not an object")
    repository_object = event.get("repository")
    pull_request = event.get("pull_request")
    if not isinstance(repository_object, dict) or not isinstance(pull_request, dict):
        raise SnapshotError("pull-request event is incomplete")
    repository = repository_object.get("full_name")
    number = pull_request.get("number")
    if (
        not isinstance(repository, str)
        or REPOSITORY.fullmatch(repository) is None
        or repository != expected_repository
        or not isinstance(number, int)
        or isinstance(number, bool)
        or number <= 0
    ):
        raise SnapshotError("pull-request event identity is invalid")
    return repository, number


def _read_event(path: Path) -> object:
    try:
        raw = read_regular_file(path, maximum=MAX_RESPONSE_BYTES)
        return json.loads(raw.decode("utf-8"))
    except (
        AgeEnvelopeError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as error:
        raise SnapshotError("pull-request event is unavailable") from error


def _fetch_live_binding(
    *,
    api_root: str,
    token: str,
    repository: str,
    pull_request: int,
) -> tuple[dict[str, object], str]:
    if (
        REPOSITORY.fullmatch(repository) is None
        or not isinstance(pull_request, int)
        or isinstance(pull_request, bool)
        or pull_request <= 0
    ):
        raise SnapshotError("pull-request API identity is invalid")
    encoded_repository = quote(repository, safe="/")
    document = _request_json(
        api_root=api_root,
        path=f"/repos/{encoded_repository}/pulls/{pull_request}",
        token=token,
    )
    if not isinstance(document, dict):
        raise SnapshotError("live pull-request response is not an object")
    base = document.get("base")
    head = document.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    live_repository = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    head_repository = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    live_number = document.get("number")
    state = document.get("state")
    if (
        live_repository != repository
        or not isinstance(head_repository, str)
        or REPOSITORY.fullmatch(head_repository) is None
        or live_number != pull_request
        or state not in {"open", "closed"}
        or not isinstance(base, dict)
        or not isinstance(head, dict)
        or not isinstance(base.get("ref"), str)
        or not isinstance(base.get("sha"), str)
        or not isinstance(head.get("sha"), str)
    ):
        raise SnapshotError("live pull-request identity is invalid")
    body = document.get("body")
    if body is not None and not isinstance(body, str):
        raise SnapshotError("live pull-request body is not text")
    if body is None:
        body = ""
    try:
        snapshot = make_snapshot(
            repository=repository,
            pull_request=pull_request,
            state=state,
            base_ref=base["ref"],
            base_commit=base["sha"],
            head_repository=head_repository,
            head_commit=head["sha"],
            body_sha256=body_digest(body),
        )
    except (AdmissionResultError, UnicodeError) as error:
        raise SnapshotError("live pull-request commits are invalid") from error
    return snapshot, body


def fetch_live_snapshot(
    *,
    api_root: str,
    token: str,
    repository: str,
    pull_request: int,
) -> dict[str, object]:
    snapshot, _ = _fetch_live_binding(
        api_root=api_root,
        token=token,
        repository=repository,
        pull_request=pull_request,
    )
    return snapshot


def fetch_live_binding(
    *,
    api_root: str,
    token: str,
    repository: str,
    pull_request: int,
) -> tuple[dict[str, object], str]:
    """Fetch the snapshot and body from one live PR response."""

    return _fetch_live_binding(
        api_root=api_root,
        token=token,
        repository=repository,
        pull_request=pull_request,
    )


def fetch_live_body(
    *,
    api_root: str,
    token: str,
    repository: str,
    pull_request: int,
) -> str:
    """Fetch the current body after the event has identified the PR."""
    _, body = fetch_live_binding(
        api_root=api_root,
        token=token,
        repository=repository,
        pull_request=pull_request,
    )
    return body


def write_body(path: Path, body: str) -> None:
    data = body.encode("utf-8")
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if not no_follow:
        raise SnapshotError("safe admission-body output is unavailable")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
            0o600,
        )
    except OSError as error:
        raise SnapshotError("admission-body output is unavailable") from error
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def write_json(path: Path, document: object) -> None:
    data = canonical_json_bytes(document) + b"\n"
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if not no_follow:
        raise SnapshotError("safe snapshot output is unavailable")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
            0o600,
        )
    except OSError as error:
        raise SnapshotError("snapshot output is unavailable") from error
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--body-output", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument(
        "--api-root",
        default=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    arguments = parser.parse_args()
    try:
        event = _read_event(arguments.event)
        repository, pull_request = event_identity(
            event,
            expected_repository=arguments.repository,
        )
        snapshot, body = fetch_live_binding(
            api_root=arguments.api_root,
            token=os.environ.get("GITHUB_TOKEN", ""),
            repository=repository,
            pull_request=pull_request,
        )
        if arguments.body_output is not None:
            if body_digest(body) != snapshot["body_sha256"]:
                raise SnapshotError("pull-request body changed during snapshot")
            write_body(
                arguments.body_output,
                body,
            )
        write_json(arguments.output, snapshot)
    except (
        SnapshotError,
        AdmissionResultError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
    ):
        # Keep the failure record bounded and free of API/error text. The
        # publisher performs its own live read before deciding whether it can
        # safely publish a failure conclusion.
        try:
            write_json(
                arguments.output,
                make_state(snapshot=None, error_code="live_snapshot_unavailable"),
            )
        except (SnapshotError, AdmissionResultError):
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
