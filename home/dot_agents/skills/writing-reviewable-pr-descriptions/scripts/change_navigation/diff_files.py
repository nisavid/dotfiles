"""Validate per-file Diff metrics."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .diff_inventory import INVENTORY_LIMIT
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
from .model import COUNT_PATTERN, POSITIVE_COUNT_PATTERN, changed_files_text

GROUP_RE = re.compile(
    rf'^- <picture><img alt="(IMPL|TEST|DOC|GEN|OTHER): ({COUNT_PATTERN}) additions?, '
    rf'({COUNT_PATTERN}) deletions?"[^>]*></picture> '
    rf'<picture><img alt="FILES: ({COUNT_PATTERN}) (shown )?'
    r"(implementation|test|documentation|generated|other) "
    r'(file|files)"[^>]*></picture>$'
)
REMAINDER_RE = re.compile(
    rf'^- <picture><img alt="REMAINDER: ({POSITIVE_COUNT_PATTERN}) '
    r'changed (file|files)"[^>]*>'
    r"</picture>$"
)
COMPARISON_RE = re.compile(
    r"^  - \[Complete immutable comparison\]\(https://github\.com/"
    r"(?P<repository>[^/\s]+/[^/\s]+)/compare/"
    r"(?P<base>[0-9a-f]{40}|[0-9a-f]{64})\.\.\."
    r"(?P<head>[0-9a-f]{40}|[0-9a-f]{64})\)$"
)
GROUP_DESCRIPTORS = {
    "IMPL": "implementation",
    "TEST": "test",
    "DOC": "documentation",
    "GEN": "generated",
    "OTHER": "other",
}
FileLine = tuple[int, str]


@dataclass
class Group:
    category: str
    additions: int
    deletions: int
    expected_files: int
    shown_label: bool
    descriptor: str
    file_noun: str
    line_number: int
    file_lines: list[FileLine] = field(default_factory=list)


@dataclass(frozen=True)
class FileOperationCounts:
    ordinary: int
    moved: int
    copied: int
    consistent: bool


def validate_diff_file_items(
    block: list[str],
    errors: list[str],
    expected_files: int | None,
    summary_metrics: dict[str, Metric],
    expected_identity: Identity | None,
    shown_files: int | None = None,
    expected_comparison: tuple[str, str] | None = None,
) -> None:
    bounded = shown_files is not None
    _validate_expansion_grammar(block, errors, bounded)
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
        if group.shown_label != bounded:
            qualifier = "must" if bounded else "must not"
            errors.append(
                f"Diff {group.category} group {qualifier} label its file count shown"
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
        if group.expected_files == 0 and (
            not bounded or (group.additions, group.deletions) == (0, 0)
        ):
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
        totals_disagree = (
            file_totals != group_totals
            if not bounded
            else any(shown > total for shown, total in zip(file_totals, group_totals))
        )
        if totals_disagree:
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
    if (
        not bounded
        and expected_files is not None
        and len(unique_files) != expected_files
    ):
        errors.append(
            f"Diff summary claims {expected_files} files but expansion lists "
            f"{len(unique_files)} unique files"
        )
    if bounded:
        rendered_rows = sum(len(group.file_lines) for group in groups)
        if (
            shown_files != INVENTORY_LIMIT
            or rendered_rows != INVENTORY_LIMIT
            or len(unique_files) != INVENTORY_LIMIT
        ):
            errors.append(
                f"bounded Diff expansion must show exactly {INVENTORY_LIMIT} "
                "distinct file rows"
            )
        if expected_files is not None and expected_files <= INVENTORY_LIMIT:
            errors.append(
                f"bounded Diff inventory requires more than {INVENTORY_LIMIT} "
                "touched files"
            )
        _validate_remainder(
            block,
            errors,
            expected_files,
            shown_files,
            expected_identity,
            expected_comparison,
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


def diff_category_metrics(block: list[str]) -> dict[str, Metric]:
    """Return positive full category totals from the expanded Diff groups."""

    return {
        group.category: (group.additions, group.deletions)
        for group in _groups(block)
        if (group.additions, group.deletions) != (0, 0)
    }


def is_bounded_inventory(block: list[str]) -> bool:
    """Return whether the Diff uses shown counts plus an explicit remainder."""

    return any(group.shown_label for group in _groups(block))


def _groups(block: list[str]) -> list[Group]:
    groups: list[Group] = []
    current: Group | None = None
    for line_number, line in enumerate(block, start=1):
        group_match = GROUP_RE.fullmatch(line)
        if group_match:
            current = Group(
                category=group_match.group(1),
                additions=int(group_match.group(2)),
                deletions=int(group_match.group(3)),
                expected_files=int(group_match.group(4)),
                shown_label=bool(group_match.group(5)),
                descriptor=group_match.group(6),
                file_noun=group_match.group(7),
                line_number=line_number,
            )
            groups.append(current)
        elif line.startswith("  - ") and current and not COMPARISON_RE.fullmatch(line):
            current.file_lines.append((line_number, line))
    return groups


def _validate_expansion_grammar(
    block: list[str], errors: list[str], bounded: bool
) -> None:
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
        elif bounded and REMAINDER_RE.fullmatch(line):
            expecting_group = True
        elif (
            bounded
            and COMPARISON_RE.fullmatch(line)
            or line.startswith("  - ")
            and not expecting_group
        ):
            continue
        else:
            errors.append(f"Diff expansion contains unsupported content: {line}")
        if line.startswith("  - "):
            continue
        if not GROUP_RE.fullmatch(line):
            expecting_group = True
    if not saw_group:
        return


def _validate_remainder(
    block: list[str],
    errors: list[str],
    total_files: int | None,
    shown_files: int | None,
    expected_identity: Identity | None,
    expected_comparison: tuple[str, str] | None,
) -> None:
    remainder_lines = [line for line in block if REMAINDER_RE.fullmatch(line)]
    comparison_lines = [line for line in block if COMPARISON_RE.fullmatch(line)]
    if len(remainder_lines) != 1 or len(comparison_lines) != 1:
        errors.append(
            "bounded Diff expansion needs one remainder and immutable comparison"
        )
        return
    significant = [line for line in block if line.strip()]
    if significant[-3:-1] != [remainder_lines[0], comparison_lines[0]]:
        errors.append(
            "bounded Diff remainder and comparison must be its final two rows"
        )
    remainder_match = REMAINDER_RE.fullmatch(remainder_lines[0])
    assert remainder_match is not None
    remainder = int(remainder_match.group(1))
    expected_noun = "file" if remainder == 1 else "files"
    if remainder_match.group(2) != expected_noun:
        errors.append(
            f"bounded Diff remainder must say {changed_files_text(remainder)}"
        )
    expected_remainder = (
        total_files - shown_files
        if total_files is not None and shown_files is not None
        else None
    )
    if remainder != expected_remainder:
        expected_text = (
            changed_files_text(expected_remainder)
            if expected_remainder is not None and expected_remainder >= 0
            else "a nonnegative changed-file count"
        )
        errors.append(
            f"bounded Diff remainder must equal {expected_text}"
        )
    comparison = COMPARISON_RE.fullmatch(comparison_lines[0])
    assert comparison is not None
    if expected_identity and comparison.group("repository") != expected_identity[0]:
        errors.append("bounded Diff comparison must use the expected repository")
    if expected_comparison is None:
        errors.append("bounded Diff validation requires declared base and head SHAs")
    elif (comparison.group("base"), comparison.group("head")) != expected_comparison:
        errors.append(
            "bounded Diff comparison SHAs must match the declared base and head"
        )
