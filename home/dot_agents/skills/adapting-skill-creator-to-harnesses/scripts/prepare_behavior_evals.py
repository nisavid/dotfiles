#!/usr/bin/env python3
"""Prepare skill-creator behavioral eval workspace files.

This script does not run agents. It expands evals/evals.json into the
workspace layout expected by skill-creator's behavioral eval flow, including
per-eval metadata, run directories, output directories, and subagent prompts.

Workspace containment treats links and mutation by other operating-system
principals as untrusted. A concurrent process running as the same principal is
outside this boundary because it already has authority to modify the workspace.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "eval"


def load_evals(skill_dir: Path) -> dict:
    return json.loads(read_scoped_text(skill_dir, "evals/evals.json"))


def read_scoped_text(skill_dir: Path, relative_path: str) -> str:
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"source path must stay within the skill directory: {relative_path}")

    directory_fds: list[int] = []
    source_fd: int | None = None
    nofollow_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    directory_flags = nofollow_flags | os.O_DIRECTORY
    source_flags = nofollow_flags | os.O_NONBLOCK
    try:
        skill_root = skill_dir.resolve(strict=True)
        directory_fds.append(os.open(skill_root, directory_flags))
        for part in path.parts[:-1]:
            directory_fds.append(
                os.open(part, directory_flags, dir_fd=directory_fds[-1])
            )
        source_fd = os.open(path.parts[-1], source_flags, dir_fd=directory_fds[-1])
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise ValueError(
                f"source path must be a regular file within the skill directory: {relative_path}"
            )
        source = os.fdopen(source_fd, encoding="utf-8")
        source_fd = None
        with source:
            return source.read()
    except OSError as error:
        raise ValueError(
            "source path must be a regular file within the skill directory: "
            f"{relative_path}: {error.strerror or error}"
        ) from error
    finally:
        if source_fd is not None:
            os.close(source_fd)
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def prompt_variants(
    *,
    skill_dir: Path,
    eval_item: dict,
) -> dict[str, str]:
    prompt_parts = [eval_item["prompt"]]
    prompt_parts.extend(read_scoped_text(skill_dir, fixture_path) for fixture_path in eval_item["fixture_paths"])
    without_skill = "\n\n".join(prompt_parts)
    with_skill = "\n\n".join([*prompt_parts, read_scoped_text(skill_dir, "SKILL.md")])
    return {"with_skill": with_skill, "without_skill": without_skill}


def normalize_root_alias(path: Path) -> Path:
    if len(path.parts) < 2:
        return path
    top_level = Path(path.anchor) / path.parts[1]
    if not top_level.is_symlink():
        return path
    try:
        return top_level.resolve(strict=True).joinpath(*path.parts[2:])
    except OSError as error:
        raise ValueError(
            f"workspace root alias cannot be resolved: {top_level}: {error.strerror or error}"
        ) from error


def validate_component(name: str) -> None:
    if not name or "\0" in name or name in {".", ".."} or Path(name).parts != (name,):
        raise ValueError(f"generated workspace name must be one path component: {name}")


def publish_directory(parent_fd: int, private_name: str, public_name: str) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    encoded_private_name = os.fsencode(private_name)
    encoded_public_name = os.fsencode(public_name)
    if sys.platform == "darwin":
        rename = library.renameatx_np
        flags = 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        rename = library.renameat2
        flags = 1  # RENAME_NOREPLACE
    else:
        raise OSError(
            errno.ENOTSUP,
            "atomic no-replace directory publication is unsupported on this platform",
        )
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    if rename(
        parent_fd,
        encoded_private_name,
        parent_fd,
        encoded_public_name,
        flags,
    ) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), public_name)


def validate_parent_mutation_boundary(parent_fd: int) -> None:
    parent_stat = os.fstat(parent_fd)
    parent_mode = parent_stat.st_mode
    writable_by_other_principals = parent_mode & (stat.S_IWGRP | stat.S_IWOTH)
    if not writable_by_other_principals:
        return
    if not parent_mode & stat.S_ISVTX:
        raise ValueError(
            "workspace parent must not be writable by other principals "
            "without sticky-bit protection"
        )
    if parent_stat.st_uid not in {0, os.geteuid()}:
        raise ValueError(
            "sticky workspace parent must be owned by a trusted principal"
        )


def create_directory(parent_fd: int, name: str) -> int:
    """Create a bound directory within the workspace mutation boundary."""
    validate_component(name)
    validate_parent_mutation_boundary(parent_fd)
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
    for _ in range(16):
        private_name = f".prepare-behavior-evals-{secrets.token_hex(16)}"
        try:
            os.mkdir(private_name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        directory_fd: int | None = None
        try:
            directory_fd = os.open(private_name, directory_flags, dir_fd=parent_fd)
            publish_directory(parent_fd, private_name, name)
            return directory_fd
        except Exception:
            if directory_fd is not None:
                os.close(directory_fd)
            try:
                os.rmdir(private_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            raise
    raise FileExistsError("could not allocate a private workspace directory")


def write_text(parent_fd: int, name: str, content: str) -> None:
    validate_component(name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    file_fd = os.open(name, flags, 0o666, dir_fd=parent_fd)
    try:
        destination = os.fdopen(file_fd, "w", encoding="utf-8")
    except Exception:
        os.close(file_fd)
        raise
    with destination:
        destination.write(content)


def eval_directory_details(eval_item: dict) -> tuple[str, str]:
    eval_name = eval_item.get("name") or slugify(eval_item["prompt"])[:48]
    directory_name = f"eval-{eval_item['id']}-{slugify(eval_name)}"
    validate_component(directory_name)
    return eval_name, directory_name


def validate_eval_directory_names(eval_items: list[dict]) -> None:
    seen: set[str] = set()
    for eval_item in eval_items:
        _, directory_name = eval_directory_details(eval_item)
        if directory_name in seen:
            raise ValueError(
                "evals must generate unique workspace directories: "
                f"{directory_name}"
            )
        seen.add(directory_name)


def validate_workspace_identity(workspace_fd: int, workspace: Path) -> None:
    try:
        path_stat = os.stat(workspace, follow_symlinks=False)
        descriptor_stat = os.fstat(workspace_fd)
    except OSError as error:
        raise ValueError(
            f"workspace path no longer identifies the created directory: {workspace}"
        ) from error
    if not stat.S_ISDIR(path_stat.st_mode) or (
        path_stat.st_dev,
        path_stat.st_ino,
    ) != (
        descriptor_stat.st_dev,
        descriptor_stat.st_ino,
    ):
        raise ValueError(
            f"workspace path no longer identifies the created directory: {workspace}"
        )


def create_workspace(workspace: Path) -> tuple[Path, int]:
    if ".." in workspace.parts:
        raise ValueError(f"workspace path must not contain parent traversal: {workspace}")
    workspace = normalize_root_alias(workspace)
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
    directory_fds: list[int] = []
    workspace_fd: int | None = None
    try:
        directory_fds.append(os.open(workspace.anchor, directory_flags))
        for part in workspace.parts[1:-1]:
            try:
                directory_fd = os.open(part, directory_flags, dir_fd=directory_fds[-1])
            except FileNotFoundError:
                directory_fd = create_directory(directory_fds[-1], part)
            directory_fds.append(directory_fd)
        workspace_fd = create_directory(directory_fds[-1], workspace.parts[-1])
    except FileExistsError:
        raise
    except OSError as error:
        raise ValueError(
            "workspace path must not contain symlinks or non-directories: "
            f"{workspace}: {error.strerror or error}"
        ) from error
    finally:
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)
    if workspace_fd is None:
        raise RuntimeError("workspace creation did not return a directory descriptor")
    return workspace, workspace_fd


def write_eval(
    workspace_fd: int,
    eval_item: dict,
    runs: int,
    prompts: dict[str, str],
) -> None:
    eval_name, eval_directory_name = eval_directory_details(eval_item)
    eval_directory_fd = create_directory(workspace_fd, eval_directory_name)

    metadata = {
        "eval_id": eval_item["id"],
        "eval_name": eval_name,
        "prompt": eval_item["prompt"],
        "assertions": eval_item.get("expectations", []),
    }
    metadata_text = json.dumps(metadata, indent=2) + "\n"
    try:
        write_text(eval_directory_fd, "eval_metadata.json", metadata_text)
        for run_kind in ("with_skill", "without_skill"):
            run_kind_fd = create_directory(eval_directory_fd, run_kind)
            try:
                for run_number in range(1, runs + 1):
                    run_fd = create_directory(run_kind_fd, f"run-{run_number}")
                    try:
                        outputs_fd = create_directory(run_fd, "outputs")
                        os.close(outputs_fd)
                        write_text(run_fd, "eval_metadata.json", metadata_text)
                        write_text(run_fd, "subagent_prompt.md", prompts[run_kind])
                    finally:
                        os.close(run_fd)
            finally:
                os.close(run_kind_fd)
    finally:
        os.close(eval_directory_fd)


def write_run_instructions(
    workspace_fd: int,
    workspace: Path,
    skill_name: str,
    runs: int,
) -> None:
    validate_workspace_identity(workspace_fd, workspace)
    instructions = f"""# Behavioral Eval Run Instructions

This workspace was generated for the `skill-creator` behavioral eval flow.

For each `eval-*` directory:

1. For every run from `run-1` through `run-{runs}`, spawn one subagent with the
   corresponding `with_skill/<run>/subagent_prompt.md`.
2. For every run from `run-1` through `run-{runs}`, spawn one baseline subagent
   with the corresponding `without_skill/<run>/subagent_prompt.md`.
3. Allow no tool use for either subagent.
4. Capture each subagent's final response and write it to that run's `outputs/response.md`.
5. Grade each run against `eval_metadata.json` assertions and save `grading.json`
   in the run directory using skill-creator's required fields:
   `expectations[].text`, `expectations[].passed`, and `expectations[].evidence`.
6. Run:

```bash
cd <skill-creator-skill-dir>
python -m scripts.aggregate_benchmark {workspace} --skill-name {skill_name}
python eval-viewer/generate_review.py {workspace} --skill-name {skill_name} --benchmark {workspace}/benchmark.json --static {workspace}/review.html
```

The static viewer at `review.html` is the human review artifact.
"""
    write_text(workspace_fd, "RUN_INSTRUCTIONS.md", instructions)
    try:
        validate_workspace_identity(workspace_fd, workspace)
    except ValueError:
        os.unlink("RUN_INSTRUCTIONS.md", dir_fd=workspace_fd)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare behavioral eval workspace")
    parser.add_argument(
        "--skill-dir",
        type=Path,
        required=True,
        help="Path to the skill directory",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Path to the iteration workspace to create",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Runs per configuration to scaffold",
    )
    args = parser.parse_args()
    if args.runs <= 0:
        parser.error("--runs must be greater than zero")

    skill_dir = args.skill_dir.resolve()
    workspace = args.workspace.absolute()
    if workspace.exists() or workspace.is_symlink():
        parser.error("--workspace must not already exist")
    try:
        data = load_evals(skill_dir)
        validate_eval_directory_names(data["evals"])
        prepared_evals = [
            (eval_item, prompt_variants(skill_dir=skill_dir, eval_item=eval_item))
            for eval_item in data["evals"]
        ]
    except ValueError as error:
        parser.error(str(error))
    try:
        workspace, workspace_fd = create_workspace(workspace)
    except FileExistsError:
        parser.error("--workspace must not already exist")
    except ValueError as error:
        parser.error(str(error))

    try:
        try:
            for eval_item, prompts in prepared_evals:
                write_eval(workspace_fd, eval_item, args.runs, prompts)

            write_run_instructions(
                workspace_fd,
                workspace,
                data["skill_name"],
                args.runs,
            )
        except (OSError, ValueError) as error:
            parser.error(f"could not populate workspace: {error}")
    finally:
        os.close(workspace_fd)
    print(f"Prepared behavioral eval workspace: {workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
