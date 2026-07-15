#!/usr/bin/env python3
from __future__ import annotations

import copy
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PUBLIC_TARGET_MODELS = frozenset(
    {
        "operator-profile",
        "engineering-principles",
        "review-pr-playbook",
    }
)


class ValidationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ValidatedCatalog:
    forbidden_literals: tuple[str, ...]


def reject(code: str) -> None:
    raise ValidationError(code)


def validate_catalog(catalog: dict[str, Any]) -> ValidatedCatalog:
    expected_top_level = {
        "schema_version",
        "contextual_models",
        "contextual_model_migrations",
        "repository_catalog",
        "workflow_catalog",
        "privacy",
    }
    version = catalog.get("schema_version")
    if type(version) is not int or version != 1:
        reject("schema_version")
    if set(catalog) != expected_top_level:
        reject("top_level_keys")

    models = catalog.get("contextual_models")
    if not isinstance(models, list) or not models:
        reject("contextual_models")
    model_ids: list[str] = []
    selector_tags: list[str] = []
    source_filter_tags: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            reject("contextual_model_entry")
        if set(model) != {"id", "selector_tag", "source_filter_tags"}:
            reject("contextual_model_keys")
        model_id = model.get("id")
        selector_tag = model.get("selector_tag")
        filter_tags = model.get("source_filter_tags")
        if not isinstance(model_id, str) or not model_id:
            reject("contextual_model_id")
        if not isinstance(selector_tag, str) or not selector_tag:
            reject("contextual_model_selector")
        if (
            not isinstance(filter_tags, list)
            or not filter_tags
            or any(not isinstance(value, str) for value in filter_tags)
        ):
            reject("contextual_model_filter")
        if len(filter_tags) != len(set(filter_tags)):
            reject("contextual_model_filter_duplicates")
        model_ids.append(model_id)
        selector_tags.append(selector_tag)
        source_filter_tags.extend(filter_tags)
    if len(model_ids) != len(set(model_ids)):
        reject("contextual_model_id_duplicates")
    if len(selector_tags) != len(set(selector_tags)):
        reject("contextual_model_selector_duplicates")

    repositories = catalog.get("repository_catalog")
    if not isinstance(repositories, dict):
        reject("repository_catalog")
    if set(repositories) != {"canonical", "aliases", "drop_aliases"}:
        reject("repository_catalog_keys")
    canonical = repositories.get("canonical")
    aliases = repositories.get("aliases")
    drop_aliases = repositories.get("drop_aliases")
    if not isinstance(canonical, list) or not canonical:
        reject("canonical_repositories")
    if len(canonical) != len(set(canonical)):
        reject("canonical_repository_duplicates")
    if any(
        not isinstance(value, str)
        or not re.fullmatch(r"repo:[a-z0-9][a-z0-9-]*", value)
        for value in canonical
    ):
        reject("canonical_repository_form")
    if not isinstance(aliases, dict):
        reject("repository_aliases")
    if any(
        not isinstance(source, str)
        or not source
        or not isinstance(target, str)
        or not target
        for source, target in aliases.items()
    ):
        reject("repository_alias_form")
    if any(target not in canonical for target in aliases.values()):
        reject("repository_alias_target")
    if (
        not isinstance(drop_aliases, list)
        or any(not isinstance(value, str) or not value for value in drop_aliases)
    ):
        reject("repository_drop_aliases")
    if len(drop_aliases) != len(set(drop_aliases)):
        reject("repository_drop_alias_duplicates")
    alias_sources = set(aliases) | set(drop_aliases)
    if set(drop_aliases) & set(aliases):
        reject("repository_alias_disposition_conflict")
    if alias_sources & set(canonical):
        reject("canonical_repository_alias_source")

    workflows = catalog.get("workflow_catalog")
    if not isinstance(workflows, dict) or set(workflows) != {"controlled"}:
        reject("workflow_catalog_keys")
    controlled_workflows = workflows.get("controlled")
    if not isinstance(controlled_workflows, list):
        reject("controlled_workflows")
    if len(controlled_workflows) != len(set(controlled_workflows)):
        reject("controlled_workflow_duplicates")
    if any(
        not isinstance(value, str)
        or not re.fullmatch(r"workflow:[a-z0-9][a-z0-9-]*", value)
        for value in controlled_workflows
    ):
        reject("controlled_workflow_form")

    controlled_selectors = set(canonical) | set(controlled_workflows)
    if any(
        value not in controlled_selectors
        for value in selector_tags + source_filter_tags
    ):
        reject("contextual_model_selector_reference")

    migrations = catalog.get("contextual_model_migrations")
    if not isinstance(migrations, list) or not migrations:
        reject("contextual_model_migrations")
    migration_sources: list[str] = []
    private_successors: list[str] = []
    resolved_target_models = set(model_ids) | set(PUBLIC_TARGET_MODELS)
    for migration in migrations:
        if not isinstance(migration, dict):
            reject("migration_entry")
        source_id = migration.get("source_id")
        disposition = migration.get("disposition")
        target_id = migration.get("target_id")
        if disposition not in {"retain", "supersede", "retire"}:
            reject("migration_disposition")
        expected_keys = (
            {"source_id", "disposition"}
            if disposition == "retire"
            else {"source_id", "disposition", "target_id"}
        )
        if set(migration) != expected_keys:
            reject("migration_keys")
        if not isinstance(source_id, str) or not source_id:
            reject("migration_source")
        if disposition == "retain" and target_id != source_id:
            reject("retain_target")
        if disposition == "supersede" and target_id == source_id:
            reject("supersede_same_id")
        if disposition in {"retain", "supersede"} and (
            not isinstance(target_id, str) or target_id not in resolved_target_models
        ):
            reject("migration_target_unresolved")
        if disposition in {"retain", "supersede"} and target_id not in PUBLIC_TARGET_MODELS:
            private_successors.append(target_id)
        migration_sources.append(source_id)
    if len(migration_sources) != len(set(migration_sources)):
        reject("migration_source_duplicates")

    privacy = catalog.get("privacy")
    if not isinstance(privacy, dict) or set(privacy) != {"public_forbidden_literals"}:
        reject("privacy_keys")
    forbidden = privacy.get("public_forbidden_literals")
    if (
        not isinstance(forbidden, list)
        or not forbidden
        or any(not isinstance(value, str) or not value for value in forbidden)
    ):
        reject("privacy_literals")
    if len(forbidden) != len(set(forbidden)):
        reject("privacy_literal_duplicates")
    required_private = (
        set(model_ids)
        | set(selector_tags)
        | set(source_filter_tags)
        | set(migration_sources)
        | set(private_successors)
        | set(canonical)
        | set(aliases)
        | set(aliases.values())
        | set(drop_aliases)
        | set(controlled_workflows)
    )
    if not required_private.issubset(forbidden):
        reject("private_guard_incomplete")

    return ValidatedCatalog(tuple(forbidden))


def synthetic_catalog() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contextual_models": [
            {
                "id": "private-runbook-v2",
                "selector_tag": "repo:synthetic",
                "source_filter_tags": ["repo:synthetic"],
            }
        ],
        "contextual_model_migrations": [
            {
                "source_id": "private-runbook-v2",
                "disposition": "retain",
                "target_id": "private-runbook-v2",
            }
        ],
        "repository_catalog": {
            "canonical": ["repo:synthetic"],
            "aliases": {"project:synthetic": "repo:synthetic"},
            "drop_aliases": ["legacy-global-repository"],
        },
        "workflow_catalog": {"controlled": ["workflow:synthetic"]},
        "privacy": {
            "public_forbidden_literals": [
                "private-runbook-v2",
                "legacy-private-runbook",
                "repo:synthetic",
                "project:synthetic",
                "legacy-global-repository",
                "workflow:synthetic",
            ]
        },
    }


def expect_valid(catalog: dict[str, Any]) -> None:
    validate_catalog(catalog)


def expect_invalid(catalog: dict[str, Any], code: str) -> None:
    try:
        validate_catalog(catalog)
    except ValidationError as error:
        if error.code != code:
            reject("synthetic_case_wrong_rejection")
    else:
        reject("synthetic_case_unexpectedly_valid")


def validate_synthetic_migration_cases() -> None:
    expect_valid(synthetic_catalog())

    empty_optional_catalogs = synthetic_catalog()
    empty_optional_catalogs["repository_catalog"]["aliases"] = {}
    empty_optional_catalogs["repository_catalog"]["drop_aliases"] = []
    empty_optional_catalogs["workflow_catalog"]["controlled"] = []
    expect_valid(empty_optional_catalogs)

    empty_alias_source = synthetic_catalog()
    empty_alias_source["repository_catalog"]["aliases"] = {
        "": "repo:synthetic"
    }
    expect_invalid(empty_alias_source, "repository_alias_form")

    boolean_version = synthetic_catalog()
    boolean_version["schema_version"] = True
    expect_invalid(boolean_version, "schema_version")

    float_version = synthetic_catalog()
    float_version["schema_version"] = 1.0
    expect_invalid(float_version, "schema_version")

    public_successor = synthetic_catalog()
    public_successor["contextual_model_migrations"] = [
        {
            "source_id": "legacy-private-runbook",
            "disposition": "supersede",
            "target_id": "review-pr-playbook",
        }
    ]
    expect_valid(public_successor)

    private_successor = synthetic_catalog()
    private_successor["contextual_model_migrations"] = [
        {
            "source_id": "legacy-private-runbook",
            "disposition": "supersede",
            "target_id": "private-runbook-v2",
        }
    ]
    expect_valid(private_successor)

    missing_private_guard = copy.deepcopy(private_successor)
    missing_private_guard["privacy"]["public_forbidden_literals"].remove(
        "private-runbook-v2"
    )
    expect_invalid(missing_private_guard, "private_guard_incomplete")

    dangling_successor = copy.deepcopy(public_successor)
    dangling_successor["contextual_model_migrations"][0]["target_id"] = (
        "missing-target-model"
    )
    expect_invalid(dangling_successor, "migration_target_unresolved")

    same_id_successor = copy.deepcopy(public_successor)
    same_id_successor["contextual_model_migrations"][0]["target_id"] = (
        "legacy-private-runbook"
    )
    expect_invalid(same_id_successor, "supersede_same_id")

    retire = synthetic_catalog()
    retire["contextual_model_migrations"] = [
        {"source_id": "legacy-private-runbook", "disposition": "retire"}
    ]
    expect_valid(retire)

    target_bearing_retire = copy.deepcopy(retire)
    target_bearing_retire["contextual_model_migrations"][0]["target_id"] = (
        "review-pr-playbook"
    )
    expect_invalid(target_bearing_retire, "migration_keys")

    canonical_map_source = synthetic_catalog()
    canonical_map_source["repository_catalog"]["aliases"] = {
        "repo:synthetic": "repo:synthetic"
    }
    expect_invalid(canonical_map_source, "canonical_repository_alias_source")

    canonical_drop_source = synthetic_catalog()
    canonical_drop_source["repository_catalog"]["drop_aliases"] = [
        "repo:synthetic"
    ]
    expect_invalid(canonical_drop_source, "canonical_repository_alias_source")


def git(repo_root: Path, *args: str, text: bool = True) -> str | bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), *args],
            text=text,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        reject("git_inspection")


def contains_forbidden(payload: bytes | str, forbidden: tuple[str, ...]) -> bool:
    text = (
        payload.decode("utf-8", errors="ignore")
        if isinstance(payload, bytes)
        else payload
    ).casefold()
    return any(value.casefold() in text for value in forbidden)


def validate_publication_range(
    repo_root: Path, publication_base: str, forbidden: tuple[str, ...]
) -> None:
    git(repo_root, "rev-parse", "--verify", publication_base)
    object_lines = git(
        repo_root, "rev-list", "--objects", f"{publication_base}..HEAD"
    ).splitlines()
    new_objects = {line.split(" ", 1)[0] for line in object_lines}
    commits = git(
        repo_root, "rev-list", "--reverse", f"{publication_base}..HEAD"
    ).splitlines()
    scanned: set[tuple[str, bytes]] = set()
    for commit in commits:
        commit_object = git(repo_root, "cat-file", "commit", commit, text=False)
        if contains_forbidden(commit_object, forbidden):
            reject("publication_range_disclosure")
        tree = git(repo_root, "ls-tree", "-r", "-z", commit, text=False)
        for record in tree.split(b"\0"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            _mode, object_type, object_id = metadata.decode("ascii").split()
            if contains_forbidden(raw_path, forbidden):
                reject("publication_range_disclosure")
            key = (object_id, raw_path)
            if (
                object_type != "blob"
                or object_id not in new_objects
                or key in scanned
            ):
                continue
            scanned.add(key)
            blob = git(repo_root, "cat-file", "blob", object_id, text=False)
            if contains_forbidden(blob, forbidden):
                reject("publication_range_disclosure")

    staged_paths = set(
        git(
            repo_root,
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMRT",
            "-z",
            "HEAD",
            text=False,
        ).split(b"\0")
    )
    staged_paths.discard(b"")
    index = git(repo_root, "ls-files", "--stage", "-z", text=False)
    for record in index.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_id, stage = metadata.decode("ascii").split()
        if stage != "0" or raw_path not in staged_paths:
            continue
        if contains_forbidden(raw_path, forbidden):
            reject("working_tree_disclosure")
        if mode != "160000":
            blob = git(repo_root, "cat-file", "blob", object_id, text=False)
            if contains_forbidden(blob, forbidden):
                reject("working_tree_disclosure")

    worktree_paths = set(
        git(
            repo_root,
            "diff",
            "--name-only",
            "--diff-filter=ACMRT",
            "-z",
            "HEAD",
            text=False,
        ).split(b"\0")
    )
    worktree_paths.update(
        git(
            repo_root,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            text=False,
        ).split(b"\0")
    )
    worktree_paths.discard(b"")
    for raw_path in worktree_paths:
        if contains_forbidden(raw_path, forbidden):
            reject("working_tree_disclosure")
        path = raw_path.decode(sys.getfilesystemencoding(), errors="surrogateescape")
        candidate = repo_root / path
        if candidate.is_symlink():
            if contains_forbidden(str(candidate.readlink()), forbidden):
                reject("working_tree_disclosure")
        elif candidate.is_file() and contains_forbidden(
            candidate.read_bytes(), forbidden
        ):
            reject("working_tree_disclosure")


def initialize_adversary_repo(root: str) -> tuple[Path, str]:
    repo = Path(root)
    subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Synthetic Test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    (repo / "base.txt").write_text("public baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "--", "base.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "base"],
        check=True,
    )
    base = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    return repo, base


def validate_age_suffix_adversaries() -> None:
    forbidden = ("synthetic-private-marker",)
    missed: list[str] = []
    for case in ("committed", "worktree"):
        with tempfile.TemporaryDirectory(prefix="hindsight-age-adversary-") as root:
            repo, base = initialize_adversary_repo(root)
            (repo / "disguised.age").write_text(
                f"{forbidden[0]}\n", encoding="utf-8"
            )
            expected_code = "working_tree_disclosure"
            if case == "committed":
                subprocess.run(
                    ["git", "-C", str(repo), "add", "--", "disguised.age"],
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", str(repo), "commit", "--quiet", "-m", "leak"],
                    check=True,
                )
                expected_code = "publication_range_disclosure"
            try:
                validate_publication_range(repo, base, forbidden)
            except ValidationError as error:
                if error.code != expected_code:
                    reject("age_suffix_wrong_rejection")
            else:
                missed.append(case)
    if missed:
        reject("age_suffix_plaintext_bypass")


def validate_publication_metadata_adversaries() -> None:
    forbidden = ("synthetic-private-marker",)
    with tempfile.TemporaryDirectory(prefix="hindsight-metadata-adversary-") as root:
        repo, base = initialize_adversary_repo(root)
        (repo / "change.txt").write_text("public change\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repo), "add", "--", "change.txt"], check=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--quiet", "-m", forbidden[0]],
            check=True,
        )
        try:
            validate_publication_range(repo, base, forbidden)
        except ValidationError as error:
            if error.code != "publication_range_disclosure":
                reject("metadata_wrong_rejection")
        else:
            reject("commit_metadata_disclosure_bypass")

    with tempfile.TemporaryDirectory(prefix="hindsight-path-adversary-") as root:
        repo, base = initialize_adversary_repo(root)
        (repo / f"{forbidden[0]}.txt").write_text("public change\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repo), "add", "--", f"{forbidden[0]}.txt"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--quiet", "-m", "public change"],
            check=True,
        )
        try:
            validate_publication_range(repo, base, forbidden)
        except ValidationError as error:
            if error.code != "publication_range_disclosure":
                reject("metadata_wrong_rejection")
        else:
            reject("tree_path_disclosure_bypass")


def validate_worktree_path_adversaries() -> None:
    forbidden = ("synthetic-private-marker",)
    with tempfile.TemporaryDirectory(prefix="hindsight-worktree-path-adversary-") as root:
        repo, base = initialize_adversary_repo(root)
        (repo / "leak\npart.age").write_text(f"{forbidden[0]}\n", encoding="utf-8")
        try:
            validate_publication_range(repo, base, forbidden)
        except ValidationError as error:
            if error.code != "working_tree_disclosure":
                reject("worktree_path_wrong_rejection")
        else:
            reject("worktree_path_disclosure_bypass")

    with tempfile.TemporaryDirectory(prefix="hindsight-worktree-link-adversary-") as root:
        repo, base = initialize_adversary_repo(root)
        (repo / "disguised-link").symlink_to(forbidden[0])
        try:
            validate_publication_range(repo, base, forbidden)
        except ValidationError as error:
            if error.code != "working_tree_disclosure":
                reject("worktree_path_wrong_rejection")
        else:
            reject("worktree_symlink_disclosure_bypass")

    for kind in ("symlink", "regular"):
        with tempfile.TemporaryDirectory(
            prefix=f"hindsight-index-{kind}-adversary-"
        ) as root:
            repo, base = initialize_adversary_repo(root)
            candidate = repo / "disguised-payload"
            if kind == "symlink":
                candidate.symlink_to(forbidden[0])
            else:
                candidate.write_text(f"{forbidden[0]}\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repo), "add", "--", "disguised-payload"],
                check=True,
            )
            candidate.unlink()
            candidate.write_text("public replacement\n", encoding="utf-8")
            try:
                validate_publication_range(repo, base, forbidden)
            except ValidationError as error:
                if error.code != "working_tree_disclosure":
                    reject("worktree_path_wrong_rejection")
            else:
                reject("index_payload_disclosure_bypass")


def main() -> int:
    if len(sys.argv) != 5:
        print("private hindsight memory control plane PRD: invalid invocation", file=sys.stderr)
        return 2
    catalog_path = Path(sys.argv[1])
    prd_path = Path(sys.argv[2])
    repo_root = Path(sys.argv[3])
    publication_base = sys.argv[4]
    try:
        validate_synthetic_migration_cases()
        validate_age_suffix_adversaries()
        validate_publication_metadata_adversaries()
        validate_worktree_path_adversaries()
        with catalog_path.open("rb") as handle:
            catalog = tomllib.load(handle)
        validated = validate_catalog(catalog)
        if contains_forbidden(prd_path.read_bytes(), validated.forbidden_literals):
            reject("public_prd_disclosure")
        validate_publication_range(
            repo_root, publication_base, validated.forbidden_literals
        )
    except (OSError, tomllib.TOMLDecodeError):
        print("private hindsight memory control plane PRD: catalog I/O failure", file=sys.stderr)
        return 1
    except ValidationError as error:
        print(
            f"private hindsight memory control plane PRD: validation failed ({error.code})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
