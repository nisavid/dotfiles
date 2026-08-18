#!/usr/bin/env python3
"""Guard one existing-PR text or ready mutation with exact state checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

from reviewable_pr_state import (
    ExpectedIdentity,
    PublicationError,
    identity_matches,
    run as _run,
    state_matches,
    stored_pr as _stored_pr,
    validate_identity_inputs,
    validate_pr_locator,
)


VALIDATOR = (
    Path.home()
    / ".agents/skills/writing-reviewable-pr-descriptions/scripts/validate_change_navigation.py"
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_body(path: Path) -> str:
    if not path.is_absolute():
        raise PublicationError("body file path must be absolute")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise PublicationError(f"cannot read body file: {error}") from error


def read_preimage(repository: str, pr_number: int) -> dict[str, str]:
    validate_pr_locator(repository, pr_number)
    stored = _stored_pr(repository, pr_number)
    title = stored.get("title")
    body = stored.get("body")
    is_draft = stored.get("isDraft")
    if (
        not isinstance(title, str)
        or not isinstance(body, str)
        or not isinstance(is_draft, bool)
    ):
        raise PublicationError("PR title/body/draft preimage is unreadable")
    return {
        "expected_title_sha256": _digest(title),
        "expected_body_sha256": _digest(body),
        "expected_state": "draft" if is_draft else "ready",
    }


def _validate_body(
    body: str,
    repository: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
) -> None:
    if not VALIDATOR.is_file():
        raise PublicationError(f"validator is missing: {VALIDATOR}")
    _run(
        [
            sys.executable,
            str(VALIDATOR),
            "/dev/stdin",
            "--repository",
            repository,
            "--pr",
            str(pr_number),
            "--base-sha",
            base_sha,
            "--head-sha",
            head_sha,
        ],
        input_text=body,
    )


def _preflight(
    *,
    expected: ExpectedIdentity,
    expected_title_sha256: str,
    expected_body_sha256: str,
    expected_draft: bool,
) -> dict[str, Any]:
    if SHA256_RE.fullmatch(expected_title_sha256) is None:
        raise PublicationError("expected title SHA-256 must be 64 lowercase hex digits")
    if SHA256_RE.fullmatch(expected_body_sha256) is None:
        raise PublicationError("expected body SHA-256 must be 64 lowercase hex digits")
    stored = _stored_pr(expected.repository, expected.pr_number)
    if stored.get("state") != "OPEN":
        raise PublicationError("PR is not open before mutation")
    if not identity_matches(stored, expected):
        raise PublicationError(
            "PR identity or pushed base/head changed before mutation"
        )
    title = stored.get("title")
    body = stored.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise PublicationError("PR title/body preimage is unreadable")
    if (
        _digest(title) != expected_title_sha256
        or _digest(body) != expected_body_sha256
    ):
        raise PublicationError(
            "PR title/body digest does not match the captured preimage"
        )
    if stored.get("isDraft") is not expected_draft:
        raise PublicationError(
            "PR draft/ready state does not match the captured preimage"
        )
    return stored


@contextmanager
def _write_temporary_body(body: str) -> Iterator[IO[str]]:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as temporary:
        temporary.write(body)
        temporary.flush()
        yield temporary


def _warn_ambiguous_success(operation: str, command_error: PublicationError) -> None:
    print(
        f"WARNING: {operation} has an ambiguous result: the command reported "
        f"{command_error}, but the exact intended state is stored",
        file=sys.stderr,
    )


def update_text(
    *,
    expected: ExpectedIdentity,
    expected_title_sha256: str,
    expected_body_sha256: str,
    expected_draft: bool,
    title: str,
    body_path: Path,
) -> dict[str, Any]:
    if not title.strip():
        raise PublicationError("title must be non-empty")
    body = _read_body(body_path)
    _validate_body(
        body,
        expected.repository,
        expected.pr_number,
        expected.base_oid,
        expected.head_oid,
    )
    before = _preflight(
        expected=expected,
        expected_title_sha256=expected_title_sha256,
        expected_body_sha256=expected_body_sha256,
        expected_draft=expected_draft,
    )
    command_error: PublicationError | None = None
    with _write_temporary_body(body) as body_file:
        try:
            _run(
                [
                    "gh",
                    "-R",
                    expected.repository,
                    "pr",
                    "edit",
                    str(expected.pr_number),
                    "--title",
                    title,
                    "--body-file",
                    body_file.name,
                ]
            )
        except PublicationError as error:
            command_error = error
    after = _stored_pr(expected.repository, expected.pr_number)
    if state_matches(
        after,
        expected,
        title=title,
        body=body,
        is_draft=expected_draft,
    ):
        if command_error is not None:
            _warn_ambiguous_success("PR text mutation", command_error)
        return after
    detail = f"; command reported: {command_error}" if command_error else ""
    if after == before:
        raise PublicationError(f"PR text mutation was not stored{detail}")
    raise PublicationError(
        "PR text mutation has an ambiguous result; no retry or rollback was "
        f"attempted{detail}"
    )


def mark_ready(
    *,
    expected: ExpectedIdentity,
    expected_title_sha256: str,
    expected_body_sha256: str,
) -> dict[str, Any]:
    validated = _preflight(
        expected=expected,
        expected_title_sha256=expected_title_sha256,
        expected_body_sha256=expected_body_sha256,
        expected_draft=True,
    )
    title = str(validated["title"])
    body = str(validated["body"])
    _validate_body(
        body,
        expected.repository,
        expected.pr_number,
        expected.base_oid,
        expected.head_oid,
    )
    before = _preflight(
        expected=expected,
        expected_title_sha256=expected_title_sha256,
        expected_body_sha256=expected_body_sha256,
        expected_draft=True,
    )
    command_error: PublicationError | None = None
    try:
        _run(
            [
                "gh",
                "-R",
                expected.repository,
                "pr",
                "ready",
                str(expected.pr_number),
            ]
        )
    except PublicationError as error:
        command_error = error
    after = _stored_pr(expected.repository, expected.pr_number)
    if state_matches(after, expected, title=title, body=body, is_draft=False):
        if command_error is not None:
            _warn_ambiguous_success("ready mutation", command_error)
        return after
    detail = f"; command reported: {command_error}" if command_error else ""
    if after == before:
        raise PublicationError(f"PR remains a verified canonical draft{detail}")
    raise PublicationError(
        "ready mutation has an ambiguous result; no retry or rollback was "
        f"attempted{detail}"
    )


def _expected(args: argparse.Namespace) -> ExpectedIdentity:
    validate_identity_inputs(
        repository=args.repository,
        pr_number=args.pr,
        base=args.base,
        base_oid=args.base_oid,
        head=args.head,
        head_oid=args.head_oid,
        head_owner=args.head_owner,
    )
    return ExpectedIdentity(
        repository=args.repository,
        pr_number=args.pr,
        base=args.base,
        base_oid=args.base_oid,
        head=args.head,
        head_oid=args.head_oid,
        head_owner=args.head_owner,
    )


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--base", required=True)
    parser.add_argument("--base-oid", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--head-oid", required=True)
    parser.add_argument("--head-owner", required=True)
    parser.add_argument("--expected-title-sha256", required=True)
    parser.add_argument("--expected-body-sha256", required=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    preimage_parser = subparsers.add_parser("preimage")
    preimage_parser.add_argument("--repository", required=True)
    preimage_parser.add_argument("--pr", required=True, type=int)
    text_parser = subparsers.add_parser("text")
    _add_common(text_parser)
    text_parser.add_argument(
        "--expected-state", choices=("draft", "ready"), required=True
    )
    text_parser.add_argument("--title", required=True)
    text_parser.add_argument("--body-file", required=True, type=Path)
    ready_parser = subparsers.add_parser("ready")
    _add_common(ready_parser)
    ready_parser.add_argument(
        "--expected-state", choices=("draft", "ready"), required=True
    )
    args = parser.parse_args()
    try:
        if args.operation == "preimage":
            result = read_preimage(args.repository, args.pr)
        elif args.operation == "text":
            expected = _expected(args)
            result = update_text(
                expected=expected,
                expected_title_sha256=args.expected_title_sha256,
                expected_body_sha256=args.expected_body_sha256,
                expected_draft=args.expected_state == "draft",
                title=args.title,
                body_path=args.body_file,
            )
        else:
            expected = _expected(args)
            if args.expected_state != "draft":
                raise PublicationError("ready mutation requires a draft preimage")
            result = mark_ready(
                expected=expected,
                expected_title_sha256=args.expected_title_sha256,
                expected_body_sha256=args.expected_body_sha256,
            )
    except PublicationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
