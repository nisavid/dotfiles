"""Validate per-file Diff metrics."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .diff_metrics import (
    FileKey,
    Identity,
    atomic_totals,
    file_identity,
    file_key,
    file_operation_kind,
    parse_file_link,
    validate_file_line,
)
from .metrics import Metric


GROUP_RE = re.compile(
    r'^- <picture><img alt="(IMPL|TEST|DOC|GEN|OTHER): (\d+) additions, '
    r'(\d+) deletions"[^>]*></picture> '
    r'<picture><img alt="FILES: (\d+) '
    r"(implementation|test|documentation|generated|other) "
    r'(file|files)"[^>]*></picture>$'
)
GROUP_DESCRIPTORS = {
    "IMPL": "implementation",
    "TEST": "test",
    "DOC": "documentation",
    "GEN": "generated",
    "OTHER": "other",
}
FileLine = Tuple[int, str]


@dataclass
class Group:
    category: str
    additions: int
    deletions: int
    expected_files: int
    descriptor: str
    file_noun: str
    line_number: int
    file_lines: List[FileLine] = field(default_factory=list)


@dataclass(frozen=True)
class FileOperationCounts:
    ordinary: int
    moved: int
    copied: int
    consistent: bool


def validate_diff_file_items(
    block: list[str],
    errors: list[str],
    expected_files: Optional[int],
    summary_metrics: dict[str, Metric],
    expected_identity: Identity | None,
) -> None:
    _validate_expansion_grammar(block, errors)
    groups = _groups(block)
    if not groups:
        errors.append("Diff expansion needs at least one category group")
        return
    unique_files: set[FileKey] = set()
    semantics_by_file: dict[FileKey, set[tuple[str, str | None]]] = {}
    identities: set[Identity] = set()
    categories = [group.category for group in groups]
    expected_categories = [
        category
        for category in ["IMPL", "TEST", "DOC", "GEN", "OTHER"]
        if category in categories
    ]
    if categories != expected_categories:
        errors.append("Diff expansion categories are not in canonical order")
    if len(categories) != len(set(categories)):
        errors.append("Diff expansion must not repeat a category group")
    for group in groups:
        if len(group.file_lines) != group.expected_files:
            errors.append(
                f"Diff {group.category} group claims {group.expected_files} files "
                f"but lists {len(group.file_lines)}"
            )
        group_files: list[FileKey] = []
        for line_number, line in group.file_lines:
            validate_file_line(line, line_number, errors, expected_identity)
            identity = file_identity(line)
            if identity:
                identities.add(identity)
            key = file_key(line)
            if key:
                group_files.append(key)
                unique_files.add(key)
                operation = file_operation_kind(line)
                link = parse_file_link(line)
                if operation and link:
                    semantics_by_file.setdefault(key, set()).add(
                        (operation, link.source_path)
                    )
        if len(group_files) != len(set(group_files)):
            errors.append(f"Diff {group.category} group must not repeat a changed file")
        if group.expected_files == 0:
            errors.append(
                f"Diff {group.category} group on line {group.line_number} must not be empty"
            )
        expected_noun = "file" if group.expected_files == 1 else "files"
        if group.file_noun != expected_noun:
            errors.append(
                f"Diff {group.category} group must use {expected_noun} for {group.expected_files}"
            )
        expected_descriptor = GROUP_DESCRIPTORS[group.category]
        if group.descriptor != expected_descriptor:
            errors.append(
                f"Diff {group.category} group must label its files {expected_descriptor}"
            )
        file_totals = atomic_totals(group.file_lines)
        group_totals = (group.additions, group.deletions)
        if file_totals != group_totals:
            errors.append(
                f"Diff {group.category} group claims {group.additions} additions and "
                f"{group.deletions} deletions but its file badges total "
                f"{file_totals[0]} additions and {file_totals[1]} deletions"
            )
        summary_totals = summary_metrics.get(group.category)
        if group_totals != (0, 0) and summary_totals != group_totals:
            errors.append(
                f"Diff {group.category} group totals do not match its summary badge"
            )
    positive_groups = {
        group.category: (group.additions, group.deletions)
        for group in groups
        if (group.additions, group.deletions) != (0, 0)
    }
    if positive_groups != summary_metrics:
        errors.append("Diff summary categories do not match expanded category totals")
    if expected_files is not None and len(unique_files) != expected_files:
        errors.append(
            f"Diff summary claims {expected_files} files but expansion lists "
            f"{len(unique_files)} unique files"
        )
    if expected_identity is None and len(identities) > 1:
        errors.append("all Diff file links must target one repository and PR")
    if any(len(semantics) > 1 for semantics in semantics_by_file.values()):
        errors.append(
            "a Diff file repeated across categories must use one operation kind "
            "and source path"
        )


def file_operation_counts(block: list[str]) -> FileOperationCounts:
    """Count unique target paths by their canonical file operation."""
    semantics_by_file: dict[FileKey, set[tuple[str, str | None]]] = {}
    for group in _groups(block):
        for _, line in group.file_lines:
            key = file_key(line)
            operation = file_operation_kind(line)
            link = parse_file_link(line)
            if key and operation and link:
                semantics_by_file.setdefault(key, set()).add(
                    (operation, link.source_path)
                )
    consistent = all(len(semantics) == 1 for semantics in semantics_by_file.values())
    kinds = [next(iter(semantics))[0] for semantics in semantics_by_file.values()]
    moved = kinds.count("MOVED")
    copied = kinds.count("COPIED")
    return FileOperationCounts(
        ordinary=len(kinds) - moved - copied,
        moved=moved,
        copied=copied,
        consistent=consistent,
    )


def _groups(block: list[str]) -> list[Group]:
    groups: list[Group] = []
    current: Optional[Group] = None
    for line_number, line in enumerate(block, start=1):
        group_match = GROUP_RE.fullmatch(line)
        if group_match:
            current = Group(
                category=group_match.group(1),
                additions=int(group_match.group(2)),
                deletions=int(group_match.group(3)),
                expected_files=int(group_match.group(4)),
                descriptor=group_match.group(5),
                file_noun=group_match.group(6),
                line_number=line_number,
            )
            groups.append(current)
        elif line.startswith("  - ") and current:
            current.file_lines.append((line_number, line))
    return groups


def _validate_expansion_grammar(block: list[str], errors: list[str]) -> None:
    significant = [line for line in block if line.strip()]
    if len(significant) < 5:
        errors.append("Diff expansion is incomplete")
        return
    content = significant[2:-1]
    expecting_group = True
    saw_group = False
    for line in content:
        if GROUP_RE.fullmatch(line):
            saw_group = True
            expecting_group = False
        elif line.startswith("  - ") and not expecting_group:
            continue
        else:
            errors.append(f"Diff expansion contains unsupported content: {line}")
        if line.startswith("  - "):
            continue
        if not GROUP_RE.fullmatch(line):
            expecting_group = True
    if not saw_group:
        return
