"""Resolve Systalyze's temporary pre-merge stack surfaces fail-closed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHELL_ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
PR_IDENTITY_KEYS = ("number", "headRefName", "headRefOid")
PR_QUERY_LIMIT = 1000
COMMAND_TIMEOUT_SECONDS = 60.0


class ContractError(Exception):
    def __init__(self, code: str, **evidence: object) -> None:
        super().__init__(code)
        self.code = code
        self.evidence = evidence


def run(
    arguments: list[str],
    *,
    cwd: Path,
    failure_code: str,
    allowed_returncodes: tuple[int, ...] = (0,),
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    github_host: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for variable in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        environment.pop(variable, None)
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "false",
            "GCM_INTERACTIVE": "never",
            "GH_PROMPT_DISABLED": "1",
            "SSH_ASKPASS": "false",
            "SSH_ASKPASS_REQUIRE": "never",
        }
    )
    if github_host is not None:
        environment["GH_HOST"] = github_host
    ssh_command = environment.get("GIT_SSH_COMMAND", "ssh")
    try:
        ssh_arguments = shlex.split(ssh_command)
    except ValueError as error:
        raise ContractError(
            failure_code,
            command=Path(arguments[0]).name,
            sshCommandInvalid=True,
        ) from error
    if not ssh_arguments:
        ssh_arguments = ["ssh"]
        ssh_command = "ssh"
    program_index = 0
    while program_index < len(ssh_arguments) and SHELL_ASSIGNMENT_PATTERN.fullmatch(
        ssh_arguments[program_index]
    ):
        program_index += 1
    if program_index < len(ssh_arguments) and Path(
        ssh_arguments[program_index]
    ).name.casefold() in {"ssh", "ssh.exe"}:
        ssh_arguments[program_index + 1 : program_index + 1] = [
            "-o",
            "BatchMode=yes",
        ]
        environment["GIT_SSH_COMMAND"] = shlex.join(ssh_arguments)
    else:
        environment["GIT_SSH_COMMAND"] = ssh_command
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise ContractError(
            failure_code,
            command=Path(arguments[0]).name,
            timeoutSeconds=timeout_seconds,
        ) from error
    except OSError as error:
        raise ContractError(
            failure_code,
            command=Path(arguments[0]).name,
            osError=type(error).__name__,
        ) from error
    if result.returncode not in allowed_returncodes:
        # Process output may contain credential-helper or remote details. Keep
        # diagnostic correlation without copying those bytes into task evidence.
        raise ContractError(
            failure_code,
            returnCode=result.returncode,
            stdoutSha256="sha256:"
            + hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
            stderrSha256="sha256:"
            + hashlib.sha256(result.stderr.encode("utf-8")).hexdigest(),
        )
    return result


def git(
    repo: Path,
    *arguments: str,
    failure_code: str = "GIT_COMMAND_FAILED",
    allowed_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    return run(
        ["git", *arguments],
        cwd=repo,
        failure_code=failure_code,
        allowed_returncodes=allowed_returncodes,
    )


def normalize_remote_url(value: str) -> str | None:
    remote_url = value.strip()
    scp_match = re.fullmatch(r"(?:[^/@]+@)?([^/:]+):(.+)", remote_url)
    if scp_match and "://" not in remote_url:
        host, path = scp_match.groups()
        return f"ssh://{host.lower()}/{path.strip('/').removesuffix('.git').lower()}"

    parsed = urlparse(remote_url)
    if parsed.scheme in {"https", "ssh"} and parsed.hostname:
        try:
            port = parsed.port
        except ValueError:
            return None
        authority = parsed.hostname.lower()
        if port is not None:
            authority += f":{port}"
        return (
            f"{parsed.scheme}://{authority}/"
            f"{parsed.path.strip('/').removesuffix('.git').lower()}"
        )
    if parsed.scheme == "file":
        return str(Path(parsed.path).resolve())
    if remote_url.startswith("/"):
        return str(Path(remote_url).resolve())
    return None


def validate_surfaces(surfaces: object) -> set[str]:
    if not isinstance(surfaces, list) or len(surfaces) != 2:
        raise ContractError("MANIFEST_INVALID")

    names: set[str] = set()
    roles: set[str] = set()
    refs: set[str] = set()
    for surface in surfaces:
        if not isinstance(surface, dict) or set(surface) != {"name", "role", "ref"}:
            raise ContractError("MANIFEST_INVALID")
        name = surface["name"]
        role = surface["role"]
        ref = surface["ref"]
        if not all(isinstance(value, str) and value for value in (name, role, ref)):
            raise ContractError("MANIFEST_INVALID")
        if not ref.startswith("refs/heads/") or any(
            character.isspace() for character in ref
        ):
            raise ContractError("MANIFEST_INVALID")
        if name in names or role in roles or ref in refs:
            raise ContractError("MANIFEST_INVALID")
        names.add(name)
        roles.add(role)
        refs.add(ref)

    if roles != {"product-base", "qa-overlay"}:
        raise ContractError("MANIFEST_INVALID")
    return names


def validate_relationships(relationships: object, names: set[str]) -> None:
    if not isinstance(relationships, list) or len(relationships) != 1:
        raise ContractError("MANIFEST_INVALID")
    for relationship in relationships:
        if not isinstance(relationship, dict) or set(relationship) != {
            "left",
            "right",
            "require",
        }:
            raise ContractError("MANIFEST_INVALID")
        if not all(
            isinstance(relationship[key], str) and relationship[key]
            for key in ("left", "right", "require")
        ):
            raise ContractError("MANIFEST_INVALID")
        if (
            relationship["left"] not in names
            or relationship["right"] not in names
            or relationship["left"] == relationship["right"]
            or relationship["require"] != "common-ancestor"
        ):
            raise ContractError("MANIFEST_INVALID")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError("MANIFEST_INVALID") from error

    required = {
        "schemaVersion",
        "repository",
        "remoteUrls",
        "surfaces",
        "relationships",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise ContractError("MANIFEST_INVALID")
    if document["schemaVersion"] != 1 or not isinstance(document["repository"], str):
        raise ContractError("MANIFEST_INVALID")
    repository_parts = document["repository"].split("/")
    if (
        len(repository_parts) != 3
        or not all(repository_parts)
        or any(character.isspace() for character in document["repository"])
    ):
        raise ContractError("MANIFEST_INVALID")
    if not isinstance(document["remoteUrls"], list) or not document["remoteUrls"]:
        raise ContractError("MANIFEST_INVALID")
    if not all(isinstance(value, str) and value for value in document["remoteUrls"]):
        raise ContractError("MANIFEST_INVALID")
    if any(normalize_remote_url(value) is None for value in document["remoteUrls"]):
        raise ContractError("MANIFEST_INVALID")

    names = validate_surfaces(document["surfaces"])
    validate_relationships(document["relationships"], names)

    return document


def verify_repository_identity(repository: str, remote_identity: str) -> str:
    host, owner, name = repository.split("/")
    parsed = urlparse(remote_identity)
    if parsed.scheme not in {"https", "ssh"}:
        # Local paths are accepted only by packaged test fixtures. Production
        # manifests bind their repository to a network remote identity.
        return host
    try:
        port = parsed.port
    except ValueError as error:
        raise ContractError("REMOTE_IDENTITY_MISMATCH") from error
    remote_host = parsed.hostname
    if remote_host is None:
        raise ContractError("REMOTE_IDENTITY_MISMATCH")
    if port is not None:
        remote_host += f":{port}"
    remote_path = parsed.path.strip("/").removesuffix(".git")
    if (
        remote_host.casefold() != host.casefold()
        or remote_path.casefold() != f"{owner}/{name}".casefold()
    ):
        raise ContractError("REMOTE_IDENTITY_MISMATCH")
    return remote_host.casefold()


def verify_remote(repo: Path, remote: str, manifest: dict[str, Any]) -> str:
    result = git(
        repo,
        "remote",
        "get-url",
        "--all",
        remote,
        failure_code="REMOTE_NOT_FOUND",
    )
    identities = [
        normalize_remote_url(line) for line in result.stdout.splitlines() if line
    ]
    expected = {
        identity
        for value in manifest["remoteUrls"]
        if (identity := normalize_remote_url(value)) is not None
    }
    if not identities or any(
        identity is None or identity not in expected for identity in identities
    ):
        raise ContractError("REMOTE_IDENTITY_MISMATCH")
    remote_identity = identities[0]
    assert remote_identity is not None
    return remote_identity


def query_aliases(
    repo: Path,
    remote: str,
    surfaces: list[dict[str, str]],
    *,
    initial: bool,
) -> dict[str, str]:
    result = git(
        repo,
        "ls-remote",
        "--refs",
        remote,
        *(surface["ref"] for surface in surfaces),
        failure_code="ALIAS_QUERY_FAILED",
    )
    observed: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2:
            observed.setdefault(fields[1], []).append(fields[0])

    resolved: dict[str, str] = {}
    for surface in surfaces:
        matches = observed.get(surface["ref"], [])
        if len(matches) != 1 or not SHA_PATTERN.fullmatch(matches[0]):
            code = (
                "ALIAS_MISSING"
                if initial and not matches
                else "ALIAS_CHANGED_DURING_RESOLUTION"
            )
            raise ContractError(
                code,
                surface=surface["name"],
                ref=surface["ref"],
                observedRefs={
                    requested["ref"]: observed.get(requested["ref"], [])
                    for requested in surfaces
                },
            )
        resolved[surface["name"]] = matches[0]
    return resolved


def fetch_immutable_objects(repo: Path, remote: str, aliases: dict[str, str]) -> None:
    git(
        repo,
        "fetch",
        "--no-tags",
        "--no-write-fetch-head",
        "--recurse-submodules=no",
        remote,
        *dict.fromkeys(aliases.values()),
        failure_code="ALIAS_OBJECT_FETCH_FAILED",
    )
    for oid in aliases.values():
        git(
            repo,
            "cat-file",
            "-e",
            f"{oid}^{{commit}}",
            failure_code="ALIAS_NOT_COMMIT",
        )


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = git(
        repo,
        "merge-base",
        "--is-ancestor",
        ancestor,
        descendant,
        failure_code="ANCESTRY_CHECK_FAILED",
        allowed_returncodes=(0, 1),
    )
    return result.returncode == 0


def find_merge_base(repo: Path, left: str, right: str) -> str:
    result = git(
        repo,
        "merge-base",
        left,
        right,
        failure_code="RELATIONSHIP_CHECK_FAILED",
        allowed_returncodes=(0, 1),
    )
    merge_base_oid = result.stdout.strip()
    if result.returncode != 0 or not SHA_PATTERN.fullmatch(merge_base_oid):
        raise ContractError("RELATIONSHIP_MISMATCH", leftOid=left, rightOid=right)
    return merge_base_oid


def verify_cached_aliases(
    repo: Path,
    remote: str,
    surfaces: list[dict[str, str]],
    aliases: dict[str, str],
) -> None:
    for surface in surfaces:
        branch = surface["ref"].removeprefix("refs/heads/")
        cached_ref = f"refs/remotes/{remote}/{branch}"
        cached = git(
            repo,
            "rev-parse",
            "--verify",
            "--quiet",
            f"{cached_ref}^{{commit}}",
            allowed_returncodes=(0, 1),
        )
        if cached.returncode == 1:
            continue
        previous_oid = cached.stdout.strip()
        current_oid = aliases[surface["name"]]
        if previous_oid != current_oid and not is_ancestor(
            repo, previous_oid, current_oid
        ):
            raise ContractError(
                "UNEXPECTED_ALIAS_REWRITE",
                surface=surface["name"],
                previousOid=previous_oid,
                currentOid=current_oid,
            )


def load_pull_requests(
    repo: Path, repository: str, github_host: str
) -> list[dict[str, Any]]:
    result = run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repository,
            "--state",
            "open",
            "--limit",
            str(PR_QUERY_LIMIT),
            "--json",
            "number,headRefName,headRefOid,baseRefName,baseRefOid,isCrossRepository,isDraft,url",
        ],
        cwd=repo,
        failure_code="PR_QUERY_FAILED",
        github_host=github_host,
    )
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ContractError("PR_QUERY_INVALID") from error
    if not isinstance(document, list) or not all(
        isinstance(entry, dict) for entry in document
    ):
        raise ContractError("PR_QUERY_INVALID")
    if len(document) >= PR_QUERY_LIMIT:
        raise ContractError("PR_QUERY_TRUNCATED", limit=PR_QUERY_LIMIT)
    return document


def bind_pull_requests(
    surfaces: list[dict[str, str]],
    aliases: dict[str, str],
    pull_requests: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    seen_numbers: set[int] = set()
    alias_branches = {
        surface["ref"].removeprefix("refs/heads/") for surface in surfaces
    }
    forbidden_alias_heads = sorted(
        {
            head
            for pull_request in pull_requests
            if isinstance((head := pull_request.get("headRefName")), str)
            and head in alias_branches
            and pull_request.get("isCrossRepository") is not True
        }
    )
    if forbidden_alias_heads:
        raise ContractError("PR_IDENTITY_MISMATCH", aliasHeads=forbidden_alias_heads)
    for surface in surfaces:
        oid = aliases[surface["name"]]
        matches = [
            pull_request
            for pull_request in pull_requests
            if pull_request.get("headRefOid") == oid
            and pull_request.get("isCrossRepository") is False
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("number"), int):
            raise ContractError(
                "PR_IDENTITY_MISMATCH",
                surface=surface["name"],
                oid=oid,
                matchCount=len(matches),
            )
        pull_request = matches[0]
        if pull_request["number"] in seen_numbers:
            raise ContractError(
                "PR_IDENTITY_MISMATCH", surface=surface["name"], oid=oid
            )
        seen_numbers.add(pull_request["number"])
        bindings[surface["name"]] = {
            key: pull_request.get(key)
            for key in (
                "number",
                "headRefName",
                "headRefOid",
                "baseRefName",
                "baseRefOid",
                "isCrossRepository",
                "isDraft",
                "url",
            )
        }
    return bindings


def pull_request_identities(
    bindings: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        name: {key: binding[key] for key in PR_IDENTITY_KEYS}
        for name, binding in bindings.items()
    }


def resolve(arguments: argparse.Namespace) -> dict[str, Any]:
    repo = Path(arguments.repo).resolve()
    manifest_path = (
        Path(__file__).resolve().parents[1] / "references" / "premerge-stack.json"
    )
    manifest = load_manifest(manifest_path)
    remote_identity = verify_remote(repo, arguments.remote, manifest)
    github_host = verify_repository_identity(manifest["repository"], remote_identity)
    surfaces = manifest["surfaces"]
    aliases = query_aliases(repo, arguments.remote, surfaces, initial=True)
    fetch_immutable_objects(repo, arguments.remote, aliases)
    verify_cached_aliases(repo, arguments.remote, surfaces, aliases)
    pull_requests = load_pull_requests(repo, manifest["repository"], github_host)
    bindings = bind_pull_requests(surfaces, aliases, pull_requests)

    relationships = []
    for relationship in manifest["relationships"]:
        left_oid = aliases[relationship["left"]]
        right_oid = aliases[relationship["right"]]
        merge_base_oid = find_merge_base(repo, left_oid, right_oid)
        relationships.append(
            {
                **relationship,
                "leftOid": left_oid,
                "rightOid": right_oid,
                "mergeBaseOid": merge_base_oid,
                "leftIsAncestorOfRight": is_ancestor(repo, left_oid, right_oid),
                "rightIsAncestorOfLeft": is_ancestor(repo, right_oid, left_oid),
            }
        )

    final_aliases = query_aliases(repo, arguments.remote, surfaces, initial=False)
    if final_aliases != aliases:
        raise ContractError(
            "ALIAS_CHANGED_DURING_RESOLUTION",
            before=aliases,
            after=final_aliases,
        )

    final_pull_requests = load_pull_requests(repo, manifest["repository"], github_host)
    final_bindings = bind_pull_requests(surfaces, aliases, final_pull_requests)
    initial_identities = pull_request_identities(bindings)
    final_identities = pull_request_identities(final_bindings)
    if final_identities != initial_identities:
        raise ContractError(
            "PR_CHANGED_DURING_RESOLUTION",
            before=initial_identities,
            after=final_identities,
        )

    aliases_after_pr_query = query_aliases(
        repo, arguments.remote, surfaces, initial=False
    )
    if aliases_after_pr_query != aliases:
        raise ContractError(
            "ALIAS_CHANGED_DURING_RESOLUTION",
            before=aliases,
            after=aliases_after_pr_query,
        )

    resolved_surfaces = {
        surface["name"]: {
            "role": surface["role"],
            "ref": surface["ref"],
            "oid": aliases[surface["name"]],
            "pullRequest": final_bindings[surface["name"]],
        }
        for surface in surfaces
    }
    return {
        "schemaVersion": 1,
        "repository": manifest["repository"],
        "remote": arguments.remote,
        "remoteIdentity": remote_identity,
        "remoteIdentityFingerprint": "sha256:"
        + hashlib.sha256(remote_identity.encode("utf-8")).hexdigest(),
        "surfaces": resolved_surfaces,
        "relationships": relationships,
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--remote", default="origin")
    return parser.parse_args()


def main() -> int:
    try:
        document = resolve(parse_arguments())
    except ContractError as error:
        print(
            json.dumps(
                {"error": {"code": error.code, "evidence": error.evidence}},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
