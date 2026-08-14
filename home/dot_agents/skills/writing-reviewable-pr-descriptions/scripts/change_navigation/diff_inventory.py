"""Plan complete or bounded per-file Diff inventories."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

INVENTORY_LIMIT = 100
Category = Literal["IMPL", "TEST", "DOC", "GEN", "OTHER"]
CATEGORY_ORDER: tuple[Category, ...] = ("IMPL", "TEST", "DOC", "GEN", "OTHER")
OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


@dataclass(frozen=True)
class ChangeFile:
    """One changed target path in deterministic source order."""

    target_path: str
    category: Category
    additions: int
    deletions: int
    source_path: str | None = None
    operation: Literal["ATOMIC", "BINARY", "MOVED", "COPIED"] = "ATOMIC"


@dataclass(frozen=True)
class DiffInventoryPlan:
    """Full-diff aggregates plus the per-file rows selected for disclosure."""

    total_files: int
    shown_files: tuple[ChangeFile, ...]
    shown_by_category: Mapping[Category, tuple[ChangeFile, ...]]
    remainder_files: int
    total_additions: int
    total_deletions: int
    category_totals: Mapping[Category, tuple[int, int]]
    comparison_url: str | None

    @property
    def bounded(self) -> bool:
        return self.remainder_files > 0


def plan_diff_inventory(
    files: Sequence[ChangeFile],
    *,
    repository: str | None = None,
    base_sha: str | None = None,
    head_sha: str | None = None,
) -> DiffInventoryPlan:
    """Select a truthful inventory without losing full-diff aggregates."""

    target_paths = [file.target_path for file in files]
    if len(target_paths) != len(set(target_paths)):
        raise ValueError("diff inventory contains a duplicate target path")
    total_files = len(files)
    shown_files = tuple(files[:INVENTORY_LIMIT])
    identity = (repository, base_sha, head_sha)
    if total_files > INVENTORY_LIMIT and not all(identity):
        raise ValueError(
            "a bounded inventory requires repository, base SHA, and head SHA"
        )
    if any(identity):
        if not all(identity):
            raise ValueError(
                "repository, base SHA, and head SHA must be supplied together"
            )
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository or ""):
            raise ValueError("repository must use OWNER/REPO")
        if OID_RE.fullmatch(base_sha or "") is None:
            raise ValueError(
                "base SHA must be 40 or 64 lowercase hexadecimal characters"
            )
        if OID_RE.fullmatch(head_sha or "") is None:
            raise ValueError(
                "head SHA must be 40 or 64 lowercase hexadecimal characters"
            )
    comparison_url = (
        f"https://github.com/{repository}/compare/{base_sha}...{head_sha}"
        if all(identity)
        else None
    )
    category_totals = {
        category: (
            sum(file.additions for file in files if file.category == category),
            sum(file.deletions for file in files if file.category == category),
        )
        for category in CATEGORY_ORDER
        if any(file.category == category for file in files)
    }
    shown_by_category = {
        category: tuple(file for file in shown_files if file.category == category)
        for category in CATEGORY_ORDER
        if any(file.category == category for file in shown_files)
        or category_totals.get(category, (0, 0)) != (0, 0)
    }
    return DiffInventoryPlan(
        total_files=total_files,
        shown_files=shown_files,
        shown_by_category=shown_by_category,
        remainder_files=total_files - len(shown_files),
        total_additions=sum(file.additions for file in files),
        total_deletions=sum(file.deletions for file in files),
        category_totals=category_totals,
        comparison_url=comparison_url,
    )
