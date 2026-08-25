#!/usr/bin/env python3
"""Publish the App-owned admission check from a trusted result envelope.

This program is intended to run only in the isolated, protected publisher job.
It receives a short-lived installation token, never an App key.  It treats
``external_id`` as reconciliation metadata and independently validates every
check-run identity before a create/update.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

_SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if _SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, _SCRIPT_DIRECTORY)

try:
    from .privacy_age_admission_result import (
        AdmissionResultError,
        CHECK_NAME,
        PullRequestSnapshot,
        canonical_json_bytes,
        external_id,
        parse_canonical_json,
        parse_external_id,
        validate_result,
        validate_snapshot,
        validate_state,
    )
    from .privacy_age_envelopes import AgeEnvelopeError, read_regular_file
    from .privacy_age_pr_snapshot import event_identity, fetch_live_snapshot
except ImportError:  # pragma: no cover - direct script execution
    from privacy_age_admission_result import (
        AdmissionResultError,
        CHECK_NAME,
        PullRequestSnapshot,
        canonical_json_bytes,
        external_id,
        parse_canonical_json,
        parse_external_id,
        validate_result,
        validate_snapshot,
        validate_state,
    )
    from privacy_age_envelopes import AgeEnvelopeError, read_regular_file
    from privacy_age_pr_snapshot import event_identity, fetch_live_snapshot

APP_ID = 4695065
API_VERSION = "2022-11-28"
MAX_PAGES = 100
MAX_RUNS = 10_000
COMMIT_ID = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_LINK_RELATION = re.compile(r"<([^<>]+)>\s*;\s*rel=\"([^\"]+)\"", re.ASCII)


class PublicationError(RuntimeError):
    """Publication could not be completed without guessing."""


class _RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise PublicationError("GitHub API redirected a token-bearing request")


_OPENER = build_opener(_RejectRedirect())


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
        raise PublicationError("pull-request event is unavailable") from error


@dataclass(frozen=True)
class Publication:
    snapshot: PullRequestSnapshot
    result: dict[str, object] | None
    conclusion: str
    failure_code: str | None

    @property
    def identity(self) -> str:
        return external_id(self.snapshot)

    @property
    def summary(self) -> str:
        if self.result is None:
            return "Admission verifier failed closed; rerun required."
        if self.result["outcome"] == "no_protected_paths_changed":
            return "No protected paths changed; no owner receipt was parsed."
        paths = self.result["protected_paths"]
        return f"Owner admission verified for {len(paths)} protected path(s)."


@dataclass(frozen=True)
class _ResponsePage:
    document: object
    headers: dict[str, str]


class GitHubClient:
    def __init__(self, *, api_root: str, token: str):
        parsed = urlparse(api_root)
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
            raise PublicationError("GitHub API endpoint is not an HTTPS origin")
        if not token:
            raise PublicationError("App installation token is unavailable")
        self.api_root = api_root.rstrip("/")
        self.token = token

    def _request_page(
        self,
        method: str,
        path_or_url: str,
        payload: object | None = None,
    ) -> _ResponsePage:
        if path_or_url.startswith("https://"):
            requested = urlparse(path_or_url)
            configured = urlparse(self.api_root)
            if (
                requested.scheme != "https"
                or requested.username is not None
                or requested.password is not None
                or requested.params
                or requested.netloc != configured.netloc
            ):
                raise PublicationError("Checks API request origin is invalid")
            url = path_or_url
        else:
            if not path_or_url.startswith("/"):
                raise PublicationError("Checks API request path is invalid")
            url = self.api_root + path_or_url
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        data = None if payload is None else canonical_json_bytes(payload)
        request = Request(url, headers=headers, data=data, method=method)
        try:
            with _OPENER.open(request, timeout=20) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise PublicationError("GitHub API response is oversized")
                return _ResponsePage(
                    document=json.loads(raw.decode("utf-8")),
                    headers={
                        str(key).lower(): str(value)
                        for key, value in response.headers.items()
                    },
                )
        except (
            HTTPError,
            URLError,
            OSError,
            TimeoutError,
            UnicodeError,
            json.JSONDecodeError,
            RecursionError,
        ) as error:
            raise PublicationError("GitHub Checks API request failed") from error

    def request(self, method: str, path_or_url: str, payload: object | None = None) -> object:
        return self._request_page(method, path_or_url, payload).document

    def get_check_run(self, *, repository: str, run_id: int) -> dict[str, object]:
        document = self.request(
            "GET",
            f"/repos/{quote(repository, safe='/')}/check-runs/{run_id}",
        )
        if not isinstance(document, dict):
            raise PublicationError("check-run response is malformed")
        return document

    def _next_page(self, headers: dict[str, str]) -> str | None:
        raw = headers.get("link", "")
        next_url: str | None = None
        for match in _LINK_RELATION.finditer(raw):
            relation = {item.strip() for item in match.group(2).split(" ") if item.strip()}
            if "next" not in relation:
                continue
            if next_url is not None:
                raise PublicationError("Checks API returned multiple next pages")
            candidate = match.group(1)
            parsed = urlparse(candidate)
            configured = urlparse(self.api_root)
            if (
                parsed.scheme != "https"
                or parsed.netloc != configured.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.params
                or parsed.fragment
            ):
                raise PublicationError("Checks API pagination origin is invalid")
            next_url = candidate
        return next_url

    def list_check_runs(self, *, repository: str, head_commit: str) -> list[dict[str, object]]:
        encoded_repository = quote(repository, safe="/")
        url = (
            f"/repos/{encoded_repository}/commits/{head_commit}/check-runs?"
            + urlencode(
                {
                    "check_name": CHECK_NAME,
                    "filter": "all",
                    "per_page": "100",
                }
            )
        )
        runs: list[dict[str, object]] = []
        seen_urls: set[str] = set()
        expected_total: int | None = None
        for _ in range(MAX_PAGES):
            if url in seen_urls:
                raise PublicationError("Checks API pagination loop")
            seen_urls.add(url)
            response = self._request_page("GET", url)
            document = response.document
            if not isinstance(document, dict) or not isinstance(document.get("check_runs"), list):
                raise PublicationError("Checks API response is malformed")
            total_count = document.get("total_count")
            if (
                not isinstance(total_count, int)
                or isinstance(total_count, bool)
                or total_count < 0
                or total_count > MAX_RUNS
            ):
                raise PublicationError("Checks API total count is malformed")
            if expected_total is None:
                expected_total = total_count
            elif total_count != expected_total:
                raise PublicationError("Checks API result changed during pagination")
            for run in document["check_runs"]:
                if not isinstance(run, dict):
                    raise PublicationError("Checks API run is malformed")
                runs.append(run)
                if len(runs) > MAX_RUNS:
                    raise PublicationError("Checks API returned too many runs")
            next_url = self._next_page(response.headers)
            if next_url is None:
                if expected_total != len(runs):
                    raise PublicationError("Checks API pagination is incomplete")
                return runs
            url = next_url
        raise PublicationError("Checks API pagination exceeded its bound")


def _app_id(run: dict[str, object]) -> int | None:
    app = run.get("app")
    if not isinstance(app, dict):
        return None
    value = app.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _run_id(run: dict[str, object]) -> int:
    value = run.get("id")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PublicationError("check-run identity is malformed")
    return value


def _run_head(run: dict[str, object]) -> str:
    value = run.get("head_sha")
    if not isinstance(value, str) or COMMIT_ID.fullmatch(value) is None:
        raise PublicationError("check-run head is malformed")
    return value


def _classify_existing_runs(
    runs: list[dict[str, object]],
    *,
    snapshot: PullRequestSnapshot,
    expected_external_id: str,
    expected_conclusion: str | None = None,
    require_exact: bool = False,
) -> int | None:
    candidates = [run for run in runs if run.get("name") == CHECK_NAME]
    exact: list[dict[str, object]] = []
    supersedable: list[dict[str, object]] = []
    for run in candidates:
        if _app_id(run) != APP_ID or _run_head(run) != snapshot.head_commit:
            raise PublicationError("conflicting check run identity")
        value = run.get("external_id")
        if value == expected_external_id:
            exact.append(run)
            continue
        try:
            prior = parse_external_id(value)
        except AdmissionResultError as error:
            # This includes legacy runs and malformed retry metadata. Never
            # silently adopt or overwrite an identity we cannot interpret.
            raise PublicationError("legacy or conflicting check run identity") from error
        if (
            prior.repository != snapshot.repository
            or prior.pull_request != snapshot.pull_request
            or prior.head_repository != snapshot.head_repository
            or prior.head_commit != snapshot.head_commit
        ):
            # A same-head run for another PR or source repository is not ours
            # to overwrite, even when its App/name match. Base and body/state
            # changes are the deterministic retarget/edit supersession case.
            raise PublicationError("legacy or conflicting check run identity")
        supersedable.append(run)
    if len(exact) + len(supersedable) > 1:
        raise PublicationError("ambiguous duplicate check runs")
    selected = exact or supersedable
    if not selected:
        return None
    if require_exact and not exact:
        raise PublicationError("check run identity was not updated")
    run = selected[0]
    if expected_conclusion is not None and (
        run.get("status") != "completed"
        or run.get("conclusion") != expected_conclusion
    ):
        raise PublicationError("check run has an unexpected terminal state")
    return _run_id(run)


def _check_payload(
    publication: Publication,
    *,
    now: str,
    include_head_sha: bool,
) -> dict[str, object]:
    conclusion = publication.conclusion
    output = {
        "title": CHECK_NAME,
        "summary": publication.summary,
        "text": "The result is bound to the repository, pull request, base, head, and body digest.",
    }
    payload = {
        "completed_at": now,
        "conclusion": conclusion,
        "external_id": publication.identity,
        "name": CHECK_NAME,
        "output": output,
        "status": "completed",
    }
    if include_head_sha:
        payload["head_sha"] = publication.snapshot.head_commit
    return payload


def _validate_published_run(
    document: object,
    *,
    snapshot: PullRequestSnapshot,
    expected_external_id: str,
    expected_conclusion: str,
) -> int:
    if not isinstance(document, dict):
        raise PublicationError("published check response is malformed")
    if (
        document.get("name") != CHECK_NAME
        or _app_id(document) != APP_ID
        or document.get("head_sha") != snapshot.head_commit
        or document.get("external_id") != expected_external_id
        or document.get("status") != "completed"
        or document.get("conclusion") != expected_conclusion
    ):
        raise PublicationError("published check identity or conclusion is wrong")
    return _run_id(document)


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def publish(
    *,
    client: GitHubClient,
    publication: Publication,
    final_snapshot: PullRequestSnapshot,
    read_api_root: str,
    read_token: str,
) -> int:
    if publication.snapshot != final_snapshot:
        raise PublicationError("live pull-request snapshot changed before publication")
    expected_external_id = external_id(final_snapshot)
    runs = client.list_check_runs(
        repository=final_snapshot.repository,
        head_commit=final_snapshot.head_commit,
    )
    existing_id = _classify_existing_runs(
        runs,
        snapshot=final_snapshot,
        expected_external_id=expected_external_id,
    )
    # This guard is deliberately after reconciliation and immediately before
    # the create/update.  A changed body, base, head, or open state aborts the
    # write rather than retargeting an old verifier result.
    before_write = validate_snapshot(
        fetch_live_snapshot(
            api_root=read_api_root,
            token=read_token,
            repository=final_snapshot.repository,
            pull_request=final_snapshot.pull_request,
        )
    )
    if before_write != final_snapshot:
        raise PublicationError("live pull-request snapshot changed before write")
    if existing_id is not None:
        # Re-fetch the selected run after the live PR guard.  A concurrent
        # delivery may have replaced its reconciliation identity between the
        # list and this update; never overwrite a run whose identity changed.
        selected = next(
            (run for run in runs if _run_id(run) == existing_id),
            None,
        )
        if selected is None or not isinstance(selected.get("external_id"), str):
            raise PublicationError("selected check run disappeared")
        current = client.get_check_run(
            repository=final_snapshot.repository,
            run_id=existing_id,
        )
        if (
            _run_id(current) != existing_id
            or current.get("name") != CHECK_NAME
            or _app_id(current) != APP_ID
            or _run_head(current) != final_snapshot.head_commit
            or current.get("external_id") != selected.get("external_id")
        ):
            raise PublicationError("selected check run identity changed before update")
    payload = _check_payload(
        publication,
        now=_now(),
        include_head_sha=existing_id is None,
    )
    if existing_id is None:
        document = client.request(
            "POST",
            f"/repos/{quote(final_snapshot.repository, safe='/')}/check-runs",
            payload,
        )
    else:
        document = client.request(
            "PATCH",
            f"/repos/{quote(final_snapshot.repository, safe='/')}/check-runs/{existing_id}",
            payload,
        )
    published_id = _validate_published_run(
        document,
        snapshot=final_snapshot,
        expected_external_id=expected_external_id,
        expected_conclusion=publication.conclusion,
    )
    # Reconcile the response through the same exact identity rules.  This
    # catches an ambiguous retry or a server-side duplicate before completion.
    after_runs = client.list_check_runs(
        repository=final_snapshot.repository,
        head_commit=final_snapshot.head_commit,
    )
    reconciled_id = _classify_existing_runs(
        after_runs,
        snapshot=final_snapshot,
        expected_external_id=expected_external_id,
        expected_conclusion=publication.conclusion,
        require_exact=True,
    )
    if reconciled_id != published_id:
        raise PublicationError("published check run could not be reconciled")
    return published_id


def load_publication(
    *,
    state_file: Path,
    expected_repository: str,
    expected_pull_request: int,
) -> Publication:
    try:
        document = parse_canonical_json(
            read_regular_file(state_file, maximum=256 * 1024)
        )
        state = validate_state(document)
    except (AgeEnvelopeError, OSError, UnicodeError, ValueError, AdmissionResultError) as error:
        raise PublicationError("verifier state is unavailable or invalid") from error
    raw_snapshot = state["snapshot"]
    if raw_snapshot is None:
        raise PublicationError("verifier state has no pull-request binding")
    snapshot = validate_snapshot(raw_snapshot)
    if snapshot.repository != expected_repository or snapshot.pull_request != expected_pull_request:
        raise PublicationError("verifier state is bound to another pull request")
    if state["state"] == "verified":
        result = validate_result(state["result"])
        if snapshot.state != "open" or snapshot.base_ref != "main":
            raise PublicationError("verified state is not merge-eligible")
        return Publication(
            snapshot=snapshot,
            result=result,
            conclusion="success",
            failure_code=None,
        )
    return Publication(
        snapshot=snapshot,
        result=None,
        conclusion="failure",
        failure_code=state["error_code"],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--api-root", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--check-name", default=CHECK_NAME)
    parser.add_argument("--app-id", type=int, default=APP_ID)
    arguments = parser.parse_args()
    if arguments.check_name != CHECK_NAME or arguments.app_id != APP_ID:
        print("admission publisher configuration is invalid", file=sys.stderr)
        return 1
    try:
        event = _read_event(arguments.event)
        repository, pull_request = event_identity(
            event,
            expected_repository=arguments.repository,
        )
        read_token = os.environ.get("GITHUB_TOKEN", "")
        token = os.environ.get("GITHUB_APP_INSTALLATION_TOKEN", "")
        client = GitHubClient(api_root=arguments.api_root, token=token)
        try:
            publication = load_publication(
                state_file=arguments.state_file,
                expected_repository=repository,
                expected_pull_request=pull_request,
            )
        except PublicationError:
            # A verifier/setup failure still needs a blocking App result. Bind
            # that failure to a fresh live snapshot; never invent commits or a
            # body digest from the triggering event.
            fallback_snapshot = validate_snapshot(
                fetch_live_snapshot(
                    api_root=arguments.api_root,
                    token=read_token,
                    repository=repository,
                    pull_request=pull_request,
                )
            )
            publication = Publication(
                snapshot=fallback_snapshot,
                result=None,
                conclusion="failure",
                failure_code="missing_verifier_result",
            )
        # This is the first guard.  The second guard is immediately before the
        # API write after reconciliation, so edited bodies and retargets cannot
        # reuse a stale successful result.
        live_document = fetch_live_snapshot(
            api_root=arguments.api_root,
            token=read_token,
            repository=repository,
            pull_request=pull_request,
        )
        live_snapshot = validate_snapshot(live_document)
        if live_snapshot != publication.snapshot:
            raise PublicationError("live pull-request snapshot changed before reconciliation")
        # Re-read immediately before success or failure publication.  The
        # publisher never writes a result for an old body/head snapshot.
        before_write = validate_snapshot(
            fetch_live_snapshot(
                api_root=arguments.api_root,
                token=read_token,
                repository=repository,
                pull_request=pull_request,
            )
        )
        if before_write != publication.snapshot:
            raise PublicationError("live pull-request snapshot changed before reconciliation")
        publish(
            client=client,
            publication=publication,
            final_snapshot=before_write,
            read_api_root=arguments.api_root,
            read_token=read_token,
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        PublicationError,
        AdmissionResultError,
        RecursionError,
    ):
        print("admission check publication failed closed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
