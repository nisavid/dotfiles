"""Read-only Git adapter for deterministic publication planning."""

import hashlib
import json
import os
import re
import secrets
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .core import PublicationRequest, RepositorySnapshot, plan_publication


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
EXPECTED_KEYS = {
    "schema_version",
    "start_head",
    "source_sha",
    "task_owned_commits",
    "adopted_commits",
    "removal_authorized_commits",
    "explicit_destination",
    "allow_create",
    "creation_base_ref",
}
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class MalformedRequest(ValueError):
    """The request does not conform to schema version 1."""


class PolicyGate(RuntimeError):
    def __init__(self, code: str, **evidence: Any):
        super().__init__(code)
        self.code = code
        self.evidence = evidence
        self.context = {}

    def retain_context(self, context: dict) -> None:
        self.context = dict(context)


def _validate_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise MalformedRequest(f"{field} must be a full 40-hex SHA")
    return value.lower()


def _validate_remote(value: Any) -> str:
    if not isinstance(value, str) or not value or CONTROL_RE.search(value):
        raise MalformedRequest("destination remote must be a nonempty control-free string")
    return value


def _validate_heads_ref(value: Any, field: str = "destination ref") -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("refs/heads/")
        or value == "refs/heads/"
        or value.startswith("-")
        or CONTROL_RE.search(value)
        or any(token in value for token in ("..", "@{", "\\", " ", "~", "^", ":", "?", "*", "["))
        or value.endswith("/")
        or value.endswith(".")
        or "//" in value
        or any(component.startswith(".") or component.endswith(".lock") for component in value.split("/"))
    ):
        raise MalformedRequest(f"{field} must be one full refs/heads/... ref")
    return value


def _sha_set(value: Any, field: str) -> frozenset:
    if not isinstance(value, list):
        raise MalformedRequest(f"{field} must be an array")
    checked = [_validate_sha(item, field) for item in value]
    if len(set(checked)) != len(checked):
        raise MalformedRequest(f"{field} must not contain duplicates")
    return frozenset(checked)


def parse_request(raw: Any) -> PublicationRequest:
    if not isinstance(raw, dict):
        raise MalformedRequest("request must be a JSON object")
    if set(raw) != EXPECTED_KEYS:
        missing = sorted(EXPECTED_KEYS - set(raw))
        extra = sorted(set(raw) - EXPECTED_KEYS)
        raise MalformedRequest(f"request fields differ from schema; missing={missing}, extra={extra}")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise MalformedRequest("schema_version must equal 1")
    if type(raw["allow_create"]) is not bool:
        raise MalformedRequest("allow_create must be boolean")

    explicit = raw["explicit_destination"]
    if explicit is not None:
        if not isinstance(explicit, dict) or set(explicit) != {"remote", "ref"}:
            raise MalformedRequest("explicit_destination must contain exactly remote and ref")
        explicit = {
            "remote": _validate_remote(explicit["remote"]),
            "ref": _validate_heads_ref(explicit["ref"]),
        }
    creation_base = raw["creation_base_ref"]
    if creation_base is not None:
        creation_base = _validate_heads_ref(creation_base, "creation_base_ref")

    return PublicationRequest(
        schema_version=1,
        start_head=_validate_sha(raw["start_head"], "start_head"),
        source_sha=_validate_sha(raw["source_sha"], "source_sha"),
        task_owned_commits=_sha_set(raw["task_owned_commits"], "task_owned_commits"),
        adopted_commits=_sha_set(raw["adopted_commits"], "adopted_commits"),
        removal_authorized_commits=_sha_set(
            raw["removal_authorized_commits"], "removal_authorized_commits"
        ),
        explicit_destination=explicit,
        allow_create=raw["allow_create"],
        creation_base_ref=creation_base,
    )


class GitRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.env = os.environ.copy()
        self.env.update({"GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"})

    def run(
        self, args: Sequence[str], check: bool = True, allowed: Sequence[int] = ()
    ) -> subprocess.CompletedProcess:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(self.path),
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check and completed.returncode != 0 and completed.returncode not in allowed:
            raise RuntimeError(
                f"git command failed ({completed.returncode}): {args[0] if args else 'git'}: "
                f"{completed.stderr.strip()}"
            )
        return completed

    def output(self, args: Sequence[str], allowed: Sequence[int] = ()) -> str:
        return self.run(args, allowed=allowed).stdout.strip()

    def config_all(self, key: str) -> List[str]:
        result = self.run(["config", "--get-all", "--", key], check=False)
        if result.returncode == 1:
            return []
        if result.returncode != 0:
            raise RuntimeError(f"unable to read Git config key {key}")
        return result.stdout.splitlines()

    def git_path(self, name: str) -> Path:
        value = Path(self.output(["rev-parse", "--git-path", name]))
        return value if value.is_absolute() else self.path / value


def _blocked(request: PublicationRequest, gate: PolicyGate) -> dict:
    destination = gate.context.get("destination")
    target = gate.context.get("target", {"present": None, "sha": None})
    return {
        "schema_version": 1,
        "status": "blocked",
        "reasons": [{"code": gate.code, "evidence": gate.evidence}],
        "source_sha": request.source_sha,
        "destination": destination,
        "target": target,
        "outgoing_shas": [],
        "target_only_shas": [],
        "fast_forward": False,
        "rewrite_required": False,
        "push": None,
        "postchecks": [],
    }


def _guard_repository(repo: GitRepository) -> None:
    inside = repo.run(["rev-parse", "--is-inside-work-tree"], check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise PolicyGate("NOT_A_WORKTREE")
    if repo.output(["rev-parse", "--is-shallow-repository"]) == "true":
        raise PolicyGate("SHALLOW_REPOSITORY")

    partial_config = repo.output(
        ["config", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.(promisor|partialclonefilter))$"],
        allowed=(1,),
    )
    partial = []
    for line in partial_config.splitlines():
        key, _, value = line.partition(" ")
        if key.lower() == "extensions.partialclone" and value:
            partial.append(key)
        elif key.endswith(".promisor") and value.lower() in ("true", "yes", "on", "1"):
            partial.append(key)
        elif key.endswith(".partialclonefilter") and value:
            partial.append(key)
    if partial:
        raise PolicyGate("PARTIAL_OR_PROMISOR_REPOSITORY", config_keys=partial)

    replace_refs = repo.output(["for-each-ref", "--format=%(refname)", "refs/replace/"])
    if replace_refs:
        raise PolicyGate("REPLACE_REFS_PRESENT", refs=replace_refs.splitlines())

    grafts = repo.git_path("info/grafts")
    if grafts.exists() and grafts.read_bytes().strip():
        raise PolicyGate("LEGACY_GRAFTS_PRESENT")

    operation_paths = (
        "MERGE_HEAD",
        "rebase-merge",
        "rebase-apply",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "BISECT_LOG",
        "sequencer",
    )
    active = [name for name in operation_paths if repo.git_path(name).exists()]
    if active:
        raise PolicyGate("GIT_OPERATION_IN_PROGRESS", markers=active)


def _ensure_commits(repo: GitRepository, request: PublicationRequest) -> None:
    for field, sha in (("start_head", request.start_head), ("source_sha", request.source_sha)):
        result = repo.run(["cat-file", "-e", f"{sha}^{{commit}}"], check=False)
        if result.returncode != 0:
            raise PolicyGate("REQUESTED_COMMIT_UNAVAILABLE", field=field, sha=sha)


def _upstream(repo: GitRepository, branch_ref: str) -> Tuple[Optional[str], Optional[str]]:
    value = repo.output(
        [
            "for-each-ref",
            "--format=%(upstream:remotename)%00%(upstream:remoteref)",
            "--",
            branch_ref,
        ]
    )
    if not value or "\x00" not in value:
        return None, None
    remote, ref = value.split("\x00", 1)
    return (remote or None), (ref or None)


def _default_push_ref(
    mode: str,
    branch_ref: str,
    selected_remote: str,
    upstream_remote: Optional[str],
    upstream_ref: Optional[str],
) -> str:
    if mode == "nothing":
        raise PolicyGate("PUSH_DEFAULT_NOTHING")
    if mode == "matching":
        raise PolicyGate("PUSH_DEFAULT_AMBIGUOUS", mode=mode)
    if mode == "current":
        return branch_ref
    if mode == "upstream":
        if not upstream_ref or upstream_remote != selected_remote:
            raise PolicyGate("PUSH_DEFAULT_AMBIGUOUS", mode=mode)
        return upstream_ref
    if mode == "simple":
        if upstream_ref is None:
            raise PolicyGate("PUSH_DEFAULT_AMBIGUOUS", mode=mode, reason="upstream_missing")
        if upstream_remote != selected_remote or upstream_ref != branch_ref:
            raise PolicyGate("PUSH_DEFAULT_AMBIGUOUS", mode=mode)
        return branch_ref
    raise PolicyGate("PUSH_DEFAULT_UNSUPPORTED", mode=mode)


def _remote_push_ref(values: List[str], branch_ref: str) -> Optional[str]:
    if not values:
        return None
    if len(values) != 1 or any("*" in value for value in values):
        raise PolicyGate("REMOTE_PUSH_AMBIGUOUS", count=len(values))
    value = values[0]
    if value.startswith("+"):
        value = value[1:]
    if ":" in value:
        source, target = value.split(":", 1)
    else:
        source, target = value, value
    aliases = {branch_ref, branch_ref[len("refs/heads/") :], "HEAD"}
    if source not in aliases:
        raise PolicyGate("REMOTE_PUSH_DOES_NOT_SELECT_CURRENT_BRANCH")
    if source in {branch_ref[len("refs/heads/") :], "HEAD"} and ":" not in value:
        target = branch_ref
    try:
        return _validate_heads_ref(target, "remote.push target")
    except MalformedRequest:
        raise PolicyGate("REMOTE_PUSH_INVALID_TARGET")


def _resolve_destination(repo: GitRepository, request: PublicationRequest) -> Tuple[str, str, dict]:
    remotes = repo.output(["remote"]).splitlines()
    if request.explicit_destination is not None:
        remote = request.explicit_destination["remote"]
        if remote not in remotes:
            raise PolicyGate("DESTINATION_REMOTE_NOT_CONFIGURED", remote=remote)
        return remote, request.explicit_destination["ref"], {"selection": "explicit"}

    branch_ref = repo.output(["symbolic-ref", "-q", "HEAD"], allowed=(1,))
    if not branch_ref.startswith("refs/heads/"):
        raise PolicyGate("DETACHED_HEAD_REQUIRES_EXPLICIT_DESTINATION")
    branch = branch_ref[len("refs/heads/") :]
    upstream_remote, upstream_ref = _upstream(repo, branch_ref)

    push_remote = repo.config_all(f"branch.{branch}.pushRemote")
    push_default_remote = repo.config_all("remote.pushDefault")
    if len(push_remote) > 1 or len(push_default_remote) > 1:
        raise PolicyGate("DESTINATION_REMOTE_AMBIGUOUS")
    if push_remote:
        remote, selection = push_remote[0], "branch.pushRemote"
    elif push_default_remote:
        remote, selection = push_default_remote[0], "remote.pushDefault"
    elif upstream_remote:
        remote, selection = upstream_remote, "upstream"
    elif len(remotes) == 1:
        remote, selection = remotes[0], "sole_remote"
    else:
        raise PolicyGate("DESTINATION_REMOTE_AMBIGUOUS", remote_count=len(remotes))
    _validate_remote(remote)
    if remote not in remotes:
        raise PolicyGate("DESTINATION_REMOTE_NOT_CONFIGURED", remote=remote)

    push_default_values = repo.config_all("push.default")
    if len(push_default_values) > 1:
        raise PolicyGate("PUSH_DEFAULT_AMBIGUOUS", count=len(push_default_values))
    mode = push_default_values[0] if push_default_values else "simple"
    default_ref = _default_push_ref(mode, branch_ref, remote, upstream_remote, upstream_ref)
    configured_ref = _remote_push_ref(repo.config_all(f"remote.{remote}.push"), branch_ref)
    if configured_ref is not None and configured_ref != default_ref:
        raise PolicyGate(
            "PUSH_TARGET_CONFLICT", remote_push_ref=configured_ref, push_default_ref=default_ref
        )
    return remote, configured_ref or default_ref, {
        "selection": selection,
        "branch_ref": branch_ref,
        "push_default": mode,
        "remote_push": repo.config_all(f"remote.{remote}.push"),
    }


def _fingerprint(endpoint: str) -> str:
    return "sha256:" + hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def _endpoint(repo: GitRepository, remote: str) -> Tuple[str, str]:
    result = repo.run(["remote", "get-url", "--push", "--all", "--", remote], check=False)
    if result.returncode != 0:
        raise PolicyGate("PUSH_ENDPOINT_UNAVAILABLE", remote=remote)
    urls = result.stdout.splitlines()
    if len(urls) != 1 or not urls[0]:
        raise PolicyGate("PUSH_ENDPOINT_AMBIGUOUS", count=len(urls))
    return urls[0], _fingerprint(urls[0])


def _probe_ref(repo: GitRepository, endpoint: str, ref: str) -> Optional[str]:
    result = repo.run(["ls-remote", "--refs", "--", endpoint, ref], check=False)
    if result.returncode != 0:
        raise PolicyGate("PUSH_ENDPOINT_PROBE_FAILED")
    lines = [line for line in result.stdout.splitlines() if line]
    if not lines:
        return None
    if len(lines) != 1:
        raise PolicyGate("REMOTE_REF_PROBE_AMBIGUOUS", ref=ref)
    fields = lines[0].split("\t", 1)
    if len(fields) != 2 or fields[1] != ref or SHA_RE.fullmatch(fields[0]) is None:
        raise PolicyGate("REMOTE_REF_PROBE_MALFORMED", ref=ref)
    return fields[0]


def _advertised_heads(repo: GitRepository, endpoint: str) -> Dict[str, str]:
    result = repo.run(["ls-remote", "--heads", "--", endpoint], check=False)
    if result.returncode != 0:
        raise PolicyGate("PUSH_ENDPOINT_PROBE_FAILED")
    heads = {}
    for line in result.stdout.splitlines():
        sha, ref = line.split("\t", 1)
        if SHA_RE.fullmatch(sha) is None or not ref.startswith("refs/heads/"):
            raise PolicyGate("REMOTE_REF_PROBE_MALFORMED")
        heads[ref] = sha
    return heads


def _delete_temp(repo: GitRepository, ref: str, expected_shas: Sequence[str]) -> None:
    current_result = repo.run(["rev-parse", "--verify", ref], check=False)
    if current_result.returncode != 0:
        raise PolicyGate("TEMP_REF_CLEANUP_FAILED", ref=ref, reason="ref_missing")
    current = current_result.stdout.strip()
    if current not in expected_shas:
        raise PolicyGate(
            "TEMP_REF_CLEANUP_FAILED", ref=ref, reason="unexpected_sha", observed_sha=current
        )
    deleted = repo.run(["update-ref", "-d", ref, current], check=False)
    if deleted.returncode != 0:
        raise PolicyGate("TEMP_REF_CLEANUP_FAILED", ref=ref, reason="delete_failed")


def _fetch_exact(
    repo: GitRepository,
    endpoint: str,
    ref: str,
    expected: str,
    reservation_sha: str,
) -> str:
    temp_ref = f"refs/codex/checkpointing/{secrets.token_hex(16)}"
    present = repo.run(["show-ref", "--verify", "--quiet", temp_ref], check=False)
    if present.returncode == 0:
        raise PolicyGate("TEMP_REF_COLLISION", ref=temp_ref)
    if present.returncode != 1:
        raise RuntimeError("unable to prove temporary ref absence")
    reserved = repo.run(
        ["update-ref", temp_ref, reservation_sha, "0" * 40], check=False
    )
    if reserved.returncode != 0:
        raise PolicyGate("TEMP_REF_COLLISION", ref=temp_ref)
    try:
        result = repo.run(
            [
                "-c",
                "maintenance.auto=false",
                "-c",
                "fetch.writeCommitGraph=false",
                "fetch",
                "--no-tags",
                "--no-write-fetch-head",
                "--no-recurse-submodules",
                "--no-auto-maintenance",
                "--",
                endpoint,
                f"+{ref}:{temp_ref}",
            ],
            check=False,
        )
        if result.returncode != 0:
            raise PolicyGate("REMOTE_REF_CHANGED_DURING_FETCH", ref=ref, expected_sha=expected)
        fetched = repo.output(["rev-parse", "--verify", f"{temp_ref}^{{commit}}"])
        if fetched != expected:
            raise PolicyGate(
                "REMOTE_REF_CHANGED_DURING_FETCH", ref=ref, expected_sha=expected, fetched_sha=fetched
            )
        return temp_ref
    except Exception:
        _delete_temp(repo, temp_ref, (reservation_sha, expected))
        raise


def _is_ancestor(repo: GitRepository, older: str, newer: str) -> bool:
    result = repo.run(["merge-base", "--is-ancestor", older, newer], check=False)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError("git merge-base failed")


def _rev_list(repo: GitRepository, expression: str) -> Tuple[str, ...]:
    value = repo.output(["rev-list", "--topo-order", "--reverse", expression, "--"])
    return tuple(value.splitlines()) if value else ()


def _config_digest(details: dict, fingerprint: str) -> str:
    safe = dict(details)
    safe["endpoint_fingerprint"] = fingerprint
    encoded = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _snapshot(repo: GitRepository, request: PublicationRequest) -> RepositorySnapshot:
    context = {}
    temp_refs = []
    try:
        try:
            remote, ref, selection = _resolve_destination(repo, request)
            context["destination"] = {
                "remote": remote,
                "ref": ref,
                "endpoint_fingerprint": None,
                "config_digest": None,
            }
            endpoint, fingerprint = _endpoint(repo, remote)
            digest = _config_digest(selection, fingerprint)
            context["destination"].update(
                {"endpoint_fingerprint": fingerprint, "config_digest": digest}
            )
            target_sha = _probe_ref(repo, endpoint, ref)
            context["target"] = {"present": target_sha is not None, "sha": target_sha}
            start_is_ancestor = _is_ancestor(repo, request.start_head, request.source_sha)
            creation_base_sha = None
            creation_base_is_ancestor = None
            creation_base_to_start = ()
            if target_sha is not None:
                target_temp = _fetch_exact(
                    repo, endpoint, ref, target_sha, request.source_sha
                )
                temp_refs.append((target_temp, (target_sha,)))
                if _probe_ref(repo, endpoint, ref) != target_sha:
                    raise PolicyGate(
                        "REMOTE_REF_CHANGED_DURING_FETCH", ref=ref, expected_sha=target_sha
                    )
                outgoing = _rev_list(repo, f"{target_temp}..{request.source_sha}")
                target_only = _rev_list(repo, f"{request.source_sha}..{target_temp}")
                target_ancestor = _is_ancestor(repo, target_temp, request.source_sha)
                start_advertised = (
                    request.start_head in _advertised_heads(repo, endpoint).values()
                )
            else:
                if _probe_ref(repo, endpoint, ref) is not None:
                    raise PolicyGate("REMOTE_REF_APPEARED_DURING_PROBE", ref=ref)
                advertised = _advertised_heads(repo, endpoint)
                start_advertised = request.start_head in advertised.values()
                baseline = request.start_head
                if not start_advertised and request.creation_base_ref is not None:
                    creation_base_sha = _probe_ref(
                        repo, endpoint, request.creation_base_ref
                    )
                    if creation_base_sha is not None:
                        base_temp = _fetch_exact(
                            repo,
                            endpoint,
                            request.creation_base_ref,
                            creation_base_sha,
                            request.source_sha,
                        )
                        temp_refs.append((base_temp, (creation_base_sha,)))
                        if (
                            _probe_ref(repo, endpoint, request.creation_base_ref)
                            != creation_base_sha
                        ):
                            raise PolicyGate(
                                "REMOTE_REF_CHANGED_DURING_FETCH",
                                ref=request.creation_base_ref,
                                expected_sha=creation_base_sha,
                            )
                        creation_base_is_ancestor = _is_ancestor(
                            repo, base_temp, request.start_head
                        )
                        if creation_base_is_ancestor:
                            creation_base_to_start = _rev_list(
                                repo, f"{base_temp}..{request.start_head}"
                            )
                            baseline = base_temp
                outgoing = _rev_list(repo, f"{baseline}..{request.source_sha}")
                target_only = ()
                target_ancestor = False

            return RepositorySnapshot(
                remote=remote,
                ref=ref,
                endpoint_fingerprint=fingerprint,
                config_digest=digest,
                target_present=target_sha is not None,
                target_sha=target_sha,
                outgoing_shas=outgoing,
                target_only_shas=target_only,
                target_is_ancestor=target_ancestor,
                start_is_ancestor=start_is_ancestor,
                start_advertised=start_advertised,
                creation_base_sha=creation_base_sha,
                creation_base_is_ancestor=creation_base_is_ancestor,
                creation_base_to_start_shas=creation_base_to_start,
            )
        finally:
            cleanup_failure = None
            for temp_ref, expected_shas in reversed(temp_refs):
                try:
                    _delete_temp(repo, temp_ref, expected_shas)
                except PolicyGate as gate:
                    if cleanup_failure is None:
                        cleanup_failure = gate
            if cleanup_failure is not None:
                raise cleanup_failure
    except PolicyGate as gate:
        gate.retain_context(context)
        raise


def plan_repository(path: Path, raw_request: Any) -> dict:
    request = raw_request if isinstance(raw_request, PublicationRequest) else parse_request(raw_request)
    repo = GitRepository(Path(path))
    try:
        _guard_repository(repo)
        _ensure_commits(repo, request)
        return plan_publication(request, _snapshot(repo, request))
    except PolicyGate as gate:
        return _blocked(request, gate)
