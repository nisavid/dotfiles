"""Validate one Diff file link plus its metric badges."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html import escape, unescape

from .model import ATOMIC_FILE_BADGE_RE, SHIELD_IMAGE_RE, alt, title


MARKDOWN_OPERATION_FILE_LINK_RE = re.compile(
    r"^  - \[`(?P<source_path>[^`]+)` → `(?P<target_path>[^`]+)`\]"
    r"\(https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<pr>\d+)/files"
    r"#diff-(?P<anchor>[0-9a-f]{64})\) "
)
MARKDOWN_FILE_LINK_RE = re.compile(
    r"^  - \[`(?P<path>[^`]+)`\]\(https://github\.com/(?P<owner>[^/]+)/"
    r"(?P<repo>[^/]+)/pull/(?P<pr>\d+)/files"
    r"#diff-(?P<anchor>[0-9a-f]{64})\) "
)
HTML_OPERATION_FILE_LINK_RE = re.compile(
    r'^  - <a href="https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/'
    r'pull/(?P<pr>\d+)/files#diff-(?P<anchor>[0-9a-f]{64})">'
    r"<code>(?P<source_path>.+?)</code> → "
    r"<code>(?P<target_path>.+?)</code></a> "
)
HTML_FILE_LINK_RE = re.compile(
    r'^  - <a href="https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/'
    r'pull/(?P<pr>\d+)/files#diff-(?P<anchor>[0-9a-f]{64})">'
    r"<code>(?P<path>.+)</code></a> "
)
Identity = tuple[str, int]
FileKey = tuple[str, int, str]


@dataclass(frozen=True)
class FileLink:
    owner: str
    repo: str
    pr: int
    source_path: str | None
    target_path: str
    anchor: str
    end: int
    html: bool


def parse_file_link(line: str) -> FileLink | None:
    markdown_operation = MARKDOWN_OPERATION_FILE_LINK_RE.match(line)
    if markdown_operation:
        return FileLink(
            owner=markdown_operation.group("owner"),
            repo=markdown_operation.group("repo"),
            pr=int(markdown_operation.group("pr")),
            source_path=markdown_operation.group("source_path"),
            target_path=markdown_operation.group("target_path"),
            anchor=markdown_operation.group("anchor"),
            end=markdown_operation.end(),
            html=False,
        )
    markdown = MARKDOWN_FILE_LINK_RE.match(line)
    if markdown:
        return FileLink(
            owner=markdown.group("owner"),
            repo=markdown.group("repo"),
            pr=int(markdown.group("pr")),
            source_path=None,
            target_path=markdown.group("path"),
            anchor=markdown.group("anchor"),
            end=markdown.end(),
            html=False,
        )
    html_operation = HTML_OPERATION_FILE_LINK_RE.match(line)
    if html_operation:
        raw_source = html_operation.group("source_path")
        raw_target = html_operation.group("target_path")
        source_path = unescape(raw_source)
        target_path = unescape(raw_target)
        if (
            raw_source != escape(source_path, quote=False)
            or raw_target != escape(target_path, quote=False)
            or "`" not in source_path + target_path
        ):
            return None
        return FileLink(
            owner=html_operation.group("owner"),
            repo=html_operation.group("repo"),
            pr=int(html_operation.group("pr")),
            source_path=source_path,
            target_path=target_path,
            anchor=html_operation.group("anchor"),
            end=html_operation.end(),
            html=True,
        )
    html = HTML_FILE_LINK_RE.match(line)
    if not html:
        return None
    raw_path = html.group("path")
    path = unescape(raw_path)
    if raw_path != escape(path, quote=False) or "`" not in path:
        return None
    return FileLink(
        owner=html.group("owner"),
        repo=html.group("repo"),
        pr=int(html.group("pr")),
        source_path=None,
        target_path=path,
        anchor=html.group("anchor"),
        end=html.end(),
        html=True,
    )


def atomic_totals(lines: list[tuple[int, str]]) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for _, line in lines:
        for match in ATOMIC_FILE_BADGE_RE.finditer(line):
            additions += int(match.group(1))
            deletions += int(match.group(2))
    return additions, deletions


def file_identity(line: str) -> Identity | None:
    key = file_key(line)
    if not key:
        return None
    return key[0], key[1]


def file_key(line: str) -> FileKey | None:
    link = parse_file_link(line)
    if not link:
        return None
    return (
        f"{link.owner}/{link.repo}",
        link.pr,
        link.target_path,
    )


def file_operation_kind(line: str) -> str | None:
    """Return the canonical operation kind represented by one file row."""
    images = SHIELD_IMAGE_RE.findall(line)
    operation_kinds = [
        kind
        for image in images
        if (kind := alt(image)) in {"BINARY", "MOVED", "COPIED"}
    ]
    if len(operation_kinds) > 1:
        return None
    return operation_kinds[0] if operation_kinds else "ATOMIC"


def validate_file_line(
    line: str,
    line_number: int,
    errors: list[str],
    expected_identity: Identity | None = None,
) -> None:
    file_link = parse_file_link(line)
    if not file_link:
        errors.append(
            f"Diff file item {line_number} needs a verified SHA-256 Files changed anchor"
        )
    else:
        identity = file_identity(line)
        if expected_identity and identity != expected_identity:
            errors.append(
                f"Diff file item {line_number} must link to PR #{expected_identity[1]} "
                f"in {expected_identity[0]}"
            )
        expected_anchor = hashlib.sha256(file_link.target_path.encode()).hexdigest()
        if file_link.anchor != expected_anchor:
            errors.append(
                f"Diff file item {line_number} anchor does not match its linked path"
            )
    atomic_count = len(ATOMIC_FILE_BADGE_RE.findall(line))
    images = SHIELD_IMAGE_RE.findall(line)
    expected_badges = " ".join(f"<picture>{image}</picture>" for image in images)
    if file_link and line[file_link.end :] != expected_badges:
        errors.append(
            f"Diff file item {line_number} must contain only its link and allowed badges"
        )
    operation_kinds = [
        kind
        for image in images
        if (kind := alt(image)) in {"BINARY", "MOVED", "COPIED"}
    ]
    if len(operation_kinds) > 1:
        errors.append(f"Diff file item {line_number} has multiple operation badges")
    operation = operation_kinds[0] if operation_kinds else ""
    has_structured_operation = bool(file_link and file_link.source_path is not None)
    has_distinct_paths = bool(
        file_link
        and file_link.source_path
        and file_link.source_path != file_link.target_path
    )
    if operation in {"MOVED", "COPIED"} and not (
        has_structured_operation and has_distinct_paths
    ):
        errors.append(
            f"Diff {operation.lower()} file item {line_number} needs distinct "
            "structured source and target paths"
        )
    elif operation not in {"MOVED", "COPIED"} and has_structured_operation:
        errors.append(
            f"Diff file item {line_number} uses structured source and target paths "
            "without MOVED or COPIED"
        )
    actual_order = tuple(
        "ATOMIC" if ATOMIC_FILE_BADGE_RE.search(image) else alt(image)
        for image in images
    )
    if not operation and actual_order != ("ATOMIC",):
        errors.append(
            f"Diff file item {line_number} needs exactly one atomic line badge "
            "and no other badges"
        )
    elif operation == "BINARY" and actual_order != ("BINARY",):
        errors.append(
            f"Diff binary file item {line_number} must contain only its BINARY badge"
        )
    elif operation in {"MOVED", "COPIED"} and actual_order not in {
        (operation,),
        (operation, "ATOMIC"),
    }:
        errors.append(
            f"Diff operation file item {line_number} must order {operation} before "
            "an optional atomic line badge and contain no other badges"
        )
    if not atomic_count and not operation:
        errors.append(
            f"Diff file item {line_number} lacks an atomic line or operation badge"
        )
    validate_metric_titles(line, line_number, bool(operation), errors)


def validate_metric_titles(
    line: str, line_number: int, has_operation: bool, errors: list[str]
) -> None:
    for image in SHIELD_IMAGE_RE.findall(line):
        atomic_match = ATOMIC_FILE_BADGE_RE.search(image)
        operation_alt = alt(image) if has_operation else ""
        if not (atomic_match or operation_alt):
            continue
        badge_alt = alt(image)
        badge_title = title(image)
        if not badge_alt or not badge_title or badge_alt != badge_title:
            errors.append(
                f"Diff file metric {line_number} needs matching alt and title"
            )
            continue
        if atomic_match:
            expected = (
                f"{atomic_match.group(1)} additions, {atomic_match.group(2)} deletions"
            )
            if badge_alt != expected:
                errors.append(
                    f"Diff file metric {line_number} accessibility text must match {expected}"
                )
