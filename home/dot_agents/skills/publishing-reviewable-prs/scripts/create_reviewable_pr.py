#!/usr/bin/env python3
"""Create a nonce-tagged draft PR and install its canonical body safely."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any

from reviewable_pr_state import (
    PR_URL_RE,
    ExpectedIdentity,
    PublicationError,
    head_base_matches,
    open_prs as _open_prs,
    run as _run,
    state_matches,
    stored_pr as _stored_pr,
    validate_identity_inputs,
)


PR_NUMBER_TOKEN = "__PUBLISHING_REVIEWABLE_PRS_PR_NUMBER__"
VALIDATOR = (
    Path.home()
    / ".agents/skills/writing-reviewable-pr-descriptions/scripts/validate_change_navigation.py"
)


def _transport_body(nonce: str) -> str:
    return (
        "<!-- publishing-reviewable-prs: canonical body pending GitHub PR identity; "
        f"transaction={nonce} -->\n"
    )


def _new_nonce() -> str:
    return secrets.token_hex(16)


def _validate(body: str, repository: str, pr_number: int) -> None:
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
        ],
        input_text=body,
    )


def _body_template(path: Path) -> str:
    if not path.is_absolute():
        raise PublicationError("body template path must be absolute")
    try:
        template = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PublicationError(f"cannot read body template: {error}") from error
    if PR_NUMBER_TOKEN not in template:
        raise PublicationError(f"body template must contain {PR_NUMBER_TOKEN}")
    return template


def _provisional_pr_number(template: str) -> int:
    existing_numbers = {
        int(match.group("pr")) for match in PR_URL_RE.finditer(template)
    }
    candidate = max(existing_numbers, default=0) + 1
    while candidate in existing_numbers:
        candidate += 1
    return candidate


def _write_temporary_body(body: str) -> tempfile.NamedTemporaryFile[str]:
    temporary = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8")
    temporary.write(body)
    temporary.flush()
    return temporary


def _matching_head_prs(
    *, repository: str, base: str, head: str, head_owner: str
) -> list[dict[str, Any]]:
    return [
        stored
        for stored in _open_prs(repository, base, head)
        if head_base_matches(stored, base=base, head=head, head_owner=head_owner)
    ]


def _recover_created(
    *,
    repository: str,
    base: str,
    base_oid: str,
    head: str,
    head_oid: str,
    head_owner: str,
    title: str,
    transport_body: str,
) -> tuple[int, str] | None:
    matches: list[dict[str, Any]] = []
    for stored in _matching_head_prs(
        repository=repository, base=base, head=head, head_owner=head_owner
    ):
        number = stored.get("number")
        if not isinstance(number, int) or number <= 0:
            continue
        expected = ExpectedIdentity(
            repository=repository,
            pr_number=number,
            base=base,
            base_oid=base_oid,
            head=head,
            head_oid=head_oid,
            head_owner=head_owner,
        )
        if state_matches(
            stored,
            expected,
            title=title,
            body=transport_body,
            is_draft=True,
        ):
            matches.append(stored)
    if len(matches) != 1:
        return None
    return int(matches[0]["number"]), str(matches[0]["url"])


def _create(
    *,
    repository: str,
    base: str,
    base_oid: str,
    head: str,
    head_oid: str,
    head_owner: str,
    title: str,
    nonce: str,
) -> tuple[int, str]:
    existing = _matching_head_prs(
        repository=repository, base=base, head=head, head_owner=head_owner
    )
    if existing:
        urls = ", ".join(str(item.get("url", "unknown URL")) for item in existing)
        raise PublicationError(f"an open PR already exists for this head/base: {urls}")

    transport_body = _transport_body(nonce)
    create_error: PublicationError | None = None
    result = None
    with _write_temporary_body(transport_body) as body_file:
        try:
            result = _run(
                [
                    "gh",
                    "-R",
                    repository,
                    "pr",
                    "create",
                    "--base",
                    base,
                    "--head",
                    head,
                    "--title",
                    title,
                    "--body-file",
                    body_file.name,
                    "--draft",
                ]
            )
        except PublicationError as error:
            create_error = error

    if result is not None:
        match = PR_URL_RE.search(result.stdout)
        if match is not None and match.group("repository") == repository:
            return int(match.group("pr")), match.group(0)
        create_error = PublicationError("gh pr create returned no expected PR URL")

    recovered = _recover_created(
        repository=repository,
        base=base,
        base_oid=base_oid,
        head=head,
        head_oid=head_oid,
        head_owner=head_owner,
        title=title,
        transport_body=transport_body,
    )
    if recovered is not None:
        return recovered
    raise PublicationError(
        f"create outcome is ambiguous and no unique nonce-tagged draft was found: "
        f"{create_error}"
    ) from create_error


def _install_canonical_draft(
    *,
    expected: ExpectedIdentity,
    title: str,
    transport_body: str,
    body: str,
) -> dict[str, Any]:
    before = _stored_pr(expected.repository, expected.pr_number)
    if not state_matches(
        before,
        expected,
        title=title,
        body=transport_body,
        is_draft=True,
    ):
        raise PublicationError(
            "canonical body was not written because the created PR no longer has "
            "the exact nonce-tagged transport state"
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
    if state_matches(after, expected, title=title, body=body, is_draft=True):
        return after
    detail = f"; command reported: {command_error}" if command_error else ""
    if state_matches(
        after,
        expected,
        title=title,
        body=transport_body,
        is_draft=True,
    ):
        raise PublicationError(f"canonical edit was not stored{detail}")
    raise PublicationError(
        "canonical edit has an ambiguous result; observed state was preserved and "
        f"requires operator inspection{detail}"
    )


def publish(
    *,
    repository: str,
    base: str,
    base_oid: str,
    head: str,
    head_oid: str,
    head_owner: str,
    title: str,
    template_path: Path,
) -> dict[str, Any]:
    validate_identity_inputs(
        repository=repository,
        pr_number=None,
        base=base,
        base_oid=base_oid,
        head=head,
        head_oid=head_oid,
        head_owner=head_owner,
    )
    if not title.strip():
        raise PublicationError("title must be non-empty")

    template = _body_template(template_path)
    provisional_pr_number = _provisional_pr_number(template)
    provisional_body = template.replace(PR_NUMBER_TOKEN, str(provisional_pr_number))
    _validate(provisional_body, repository, provisional_pr_number)

    nonce = _new_nonce()
    transport_body = _transport_body(nonce)
    pr_number, url = _create(
        repository=repository,
        base=base,
        base_oid=base_oid,
        head=head,
        head_oid=head_oid,
        head_owner=head_owner,
        title=title,
        nonce=nonce,
    )
    expected = ExpectedIdentity(
        repository=repository,
        pr_number=pr_number,
        base=base,
        base_oid=base_oid,
        head=head,
        head_oid=head_oid,
        head_owner=head_owner,
    )
    body = template.replace(PR_NUMBER_TOKEN, str(pr_number))
    try:
        created = _stored_pr(repository, pr_number)
        if not state_matches(
            created,
            expected,
            title=title,
            body=transport_body,
            is_draft=True,
        ):
            raise PublicationError(
                "created PR does not have the exact nonce-tagged transport state"
            )
        _validate(body, repository, pr_number)
        stored = _install_canonical_draft(
            expected=expected,
            title=title,
            transport_body=transport_body,
            body=body,
        )
        return stored
    except PublicationError as error:
        raise PublicationError(
            f"PR {url} requires inspection; no automatic retry or rollback was "
            f"attempted: {error}"
        ) from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--base-oid", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--head-oid", required=True)
    parser.add_argument("--head-owner", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-template", required=True, type=Path)
    args = parser.parse_args()
    try:
        stored = publish(
            repository=args.repository,
            base=args.base,
            base_oid=args.base_oid,
            head=args.head,
            head_oid=args.head_oid,
            head_owner=args.head_owner,
            title=args.title,
            template_path=args.body_template,
        )
    except PublicationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(stored, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
