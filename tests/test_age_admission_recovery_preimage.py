from __future__ import annotations

import copy
import hashlib
import json
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "scripts/prepare-age-admission-recovery-preimage"
RECOVERY_RUNBOOK = ROOT / "docs/secret-injection/PROTON_PASS_AGE_ADMISSION.md"
RECOVERY_GH_FIXTURE = ROOT / "tests/fixtures/age-admission-recovery/gh"
BASE_COMMIT = "a" * 40
REVIEWED_SOURCE_COMMIT = "b" * 40
HEAD_COMMIT = "c" * 40
EXCEPTION_CONTEXT = "Verify trusted base against candidate data"
REQUIRED_CHECKS = [
    {"context": "check conventional commit compliance", "app_id": 15368},
    {"context": "CodeRabbit", "app_id": 347564},
    {"context": "Greptile Review", "app_id": 867647},
    {"context": "zsh deployment portability", "app_id": 15368},
    {"context": EXCEPTION_CONTEXT, "app_id": 15368},
]
GRAPHQL_QUERY = """query Issue286RecoveryReviewThreads(
  $owner: String!
  $name: String!
  $pullNumber: Int!
  $threadsCursor: String
) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pullNumber) {
      number
      baseRefOid
      headRefOid
      reviewThreads(first: 100, after: $threadsCursor) {
        nodes {
          id
          isResolved
          isOutdated
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}"""
GRAPHQL_QUERY_SHA256 = (
    "c1d9596eead2a652ce7f33120b48e03b7aaf533f2f5b719a88dd74196f631d54"
)
PUBLIC_CHECK_RUN_ID = 100_415_257_548
FIRST_ID_OVER_SIGNED_32_BIT = 2_147_483_648
PAYLOAD_ARTIFACT_MAX_BYTES = 4_194_304
REQUIRED_SUPPORT_TOOLS = (
    "awk",
    "cat",
    "cmp",
    "cp",
    "jq",
    "mv",
    "sleep",
    "stat",
    "zsh",
)
HASH_SUPPORT_TOOLS = ("shasum", "sha256sum")


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RecoveryPreimageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="age-admission-recovery-preimage."
        )
        self.private = Path(self.temporary.name).resolve(strict=True)
        self.private.chmod(0o700)
        self.bin = self.private / "bin"
        self.bin.mkdir(mode=0o700)
        self.support_bin = self.private / "support-bin"
        self.support_bin.mkdir(mode=0o700)
        self.python_tool_cache = self.private / "setup-python-tool-cache"
        self.python_tool_cache.mkdir(mode=0o700)
        self.python_launcher = self.python_tool_cache / "python3"
        self.python_launcher.symlink_to(Path(sys.executable).resolve(strict=True))
        self.support_tools = self._install_support_tools()
        self.zsh = self.support_tools["zsh"]
        self.calls = self.private / "calls.jsonl"
        self.child_ready = self.private / "child-ready.json"
        self.graphql_inputs = self.private / "graphql-inputs.jsonl"
        self.control = self.private / "control.json"
        self.counter = self.private / "counter.json"
        self.fixture = self.private / "fixture.json"
        self.request = self.private / "request.json"
        self.state = self.private / "state"
        self._write_fixture()
        self._write_fake_gh()
        self._write_request()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _install_support_tools(self) -> dict[str, Path]:
        resolved: dict[str, Path] = {"python3": self.python_launcher}
        for name in REQUIRED_SUPPORT_TOOLS:
            candidate = shutil.which(name)
            if candidate is None:
                self.fail(f"required support tool is unavailable: {name}")
            target = Path(candidate).resolve(strict=True)
            (self.support_bin / name).symlink_to(target)
            resolved[name] = target
        for name in HASH_SUPPORT_TOOLS:
            candidate = shutil.which(name)
            if candidate is None:
                continue
            target = Path(candidate).resolve(strict=True)
            (self.support_bin / name).symlink_to(target)
            resolved[name] = target
            break
        else:
            self.fail("required SHA-256 support tool is unavailable")
        (self.support_bin / "python3").symlink_to(self.python_launcher)
        return resolved

    def _protection(self) -> dict[str, object]:
        root = "https://api.github.com/repos/nisavid/dotfiles/branches/main/protection"
        return {
            "url": root,
            "required_status_checks": {
                "url": f"{root}/required_status_checks",
                "strict": True,
                "contexts": [check["context"] for check in REQUIRED_CHECKS],
                "contexts_url": f"{root}/required_status_checks/contexts",
                "checks": REQUIRED_CHECKS,
            },
            "required_pull_request_reviews": {
                "url": f"{root}/required_pull_request_reviews",
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": False,
                "require_last_push_approval": False,
                "required_approving_review_count": 1,
            },
            "required_signatures": {
                "url": f"{root}/required_signatures",
                "enabled": False,
            },
            "enforce_admins": {"url": f"{root}/enforce_admins", "enabled": True},
            "required_linear_history": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "block_creations": {"enabled": False},
            "required_conversation_resolution": {"enabled": True},
            "lock_branch": {"enabled": False},
            "allow_fork_syncing": {"enabled": False},
        }

    def _fixture_value(self) -> dict[str, object]:
        check_runs = []
        for index, check in enumerate(REQUIRED_CHECKS, start=1):
            check_runs.append(
                {
                    "id": index,
                    "name": check["context"],
                    "head_sha": HEAD_COMMIT,
                    "status": "completed",
                    "conclusion": (
                        "failure"
                        if check["context"] == EXCEPTION_CONTEXT
                        else "success"
                    ),
                    "app": {"id": check["app_id"]},
                }
            )
        return {
            "pull": {
                "number": 286,
                "state": "open",
                "merged": False,
                "draft": False,
                "auto_merge": None,
                "mergeable": True,
                "mergeable_state": "blocked",
                "commits": 2,
                "user": {"id": 1, "login": "fixture-author"},
                "base": {
                    "ref": "main",
                    "sha": BASE_COMMIT,
                    "repo": {"full_name": "nisavid/dotfiles"},
                },
                "head": {
                    "ref": "ivan/fixture-recovery",
                    "sha": HEAD_COMMIT,
                    "repo": {"full_name": "nisavid/dotfiles"},
                },
            },
            "main_ref": {
                "ref": "refs/heads/main",
                "object": {"type": "commit", "sha": BASE_COMMIT},
            },
            "pull_head_ref": {
                "ref": "refs/pull/286/head",
                "object": {"type": "commit", "sha": HEAD_COMMIT},
            },
            "commits": [
                {"sha": REVIEWED_SOURCE_COMMIT},
                {"sha": HEAD_COMMIT},
            ],
            "reviews": [
                {
                    "id": 91,
                    "state": "APPROVED",
                    "commit_id": HEAD_COMMIT,
                    "submitted_at": "2026-09-16T03:00:00Z",
                    "author_association": "COLLABORATOR",
                    "user": {"id": 2, "login": "fixture-reviewer"},
                }
            ],
            "review_threads": [
                {"id": "PRRT_resolved", "isResolved": True, "isOutdated": False}
            ],
            "requested_reviewers": {"users": [], "teams": []},
            "check_runs": {"total_count": len(check_runs), "check_runs": check_runs},
            "protection": self._protection(),
            "effective_rules": [],
            "rulesets": [],
        }

    def _write_fixture(self) -> None:
        self.fixture.write_bytes(_json_bytes(self._fixture_value()))
        self.control.write_bytes(_json_bytes({"scenario": "success"}))
        self.counter.write_bytes(_json_bytes({}))

    def _write_fake_gh(self) -> None:
        fake = self.bin / "gh"
        fake.write_text(
            textwrap.dedent(f"""\
                #!{self.python_launcher}
                from __future__ import annotations

                import json
                import os
                import sys
                from pathlib import Path
                from urllib.parse import parse_qs

                fixture_path = Path({os.fspath(self.fixture)!r})
                control_path = Path({os.fspath(self.control)!r})
                counter_path = Path({os.fspath(self.counter)!r})
                calls_path = Path({os.fspath(self.calls)!r})
                child_ready_path = Path({os.fspath(self.child_ready)!r})
                graphql_inputs_path = Path({os.fspath(self.graphql_inputs)!r})
                expected_query = {GRAPHQL_QUERY!r}

                if any(
                    os.environ.get(name)
                    for name in (
                        "GH_TOKEN",
                        "GITHUB_TOKEN",
                        "GH_ENTERPRISE_TOKEN",
                        "GITHUB_ENTERPRISE_TOKEN",
                    )
                ):
                    raise SystemExit(89)

                args = sys.argv[1:]
                with calls_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(args, separators=(",", ":")) + "\\n")
                if not args or args[0] != "api":
                    raise SystemExit(90)
                if "--method" not in args:
                    raise SystemExit(91)
                method = args[args.index("--method") + 1]
                if "--hostname" not in args or args[args.index("--hostname") + 1] != "github.com":
                    raise SystemExit(92)
                endpoint = args[-1]
                path, _, query = endpoint.partition("?")
                parameters = parse_qs(query)
                page = int(parameters.get("page", ["1"])[0])

                fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                scenario = json.loads(control_path.read_text(encoding="utf-8"))["scenario"]
                counters = json.loads(counter_path.read_text(encoding="utf-8"))
                counters[path] = counters.get(path, 0) + 1
                counter_path.write_text(
                    json.dumps(counters, sort_keys=True, separators=(",", ":")) + "\\n",
                    encoding="utf-8",
                )

                if method == "POST":
                    if endpoint != "graphql" or args[-3:-1] != ["--input", "-"]:
                        raise SystemExit(94)
                    request = json.load(sys.stdin)
                    with graphql_inputs_path.open("a", encoding="utf-8") as stream:
                        stream.write(
                            json.dumps(request, sort_keys=True, separators=(",", ":"))
                            + "\\n"
                        )
                    if set(request) != {{"query", "variables"}} or request["query"] != expected_query:
                        raise SystemExit(95)
                    variables = request["variables"]
                    if set(variables) != {{"owner", "name", "pullNumber", "threadsCursor"}}:
                        raise SystemExit(96)
                    if {{key: value for key, value in variables.items() if key != "threadsCursor"}} != {{
                        "owner": "nisavid",
                        "name": "dotfiles",
                        "pullNumber": 286,
                    }}:
                        raise SystemExit(97)
                    cursor = variables["threadsCursor"]
                    threads = fixture["review_threads"]
                    has_next = False
                    end_cursor = "fixture-end"
                    if scenario == "graphql-pagination":
                        if cursor is None:
                            threads = [threads[0]]
                            has_next = True
                            end_cursor = "fixture-page-one"
                        elif cursor == "fixture-page-one":
                            threads = [
                                {{
                                    "id": "PRRT_resolved_outdated",
                                    "isResolved": True,
                                    "isOutdated": True,
                                }}
                            ]
                            end_cursor = "fixture-page-two"
                        else:
                            raise SystemExit(99)
                    elif cursor is not None:
                        raise SystemExit(99)
                    if scenario == "graphql-unresolved-outdated":
                        threads = [
                            {{
                                "id": "PRRT_unresolved_outdated",
                                "isResolved": False,
                                "isOutdated": True,
                            }}
                        ]
                    if scenario == "graphql-errors":
                        value = {{"data": None, "errors": [{{"message": "fixture"}}]}}
                        sys.stdout.write(
                            json.dumps(value, sort_keys=True, separators=(",", ":"))
                            + "\\n"
                        )
                        raise SystemExit(0)
                    value = {{
                        "data": {{
                            "repository": {{
                                "pullRequest": {{
                                    "number": 286,
                                    "baseRefOid": {BASE_COMMIT!r},
                                    "headRefOid": {HEAD_COMMIT!r},
                                    "reviewThreads": {{
                                        "nodes": threads,
                                        "pageInfo": {{
                                            "hasNextPage": has_next,
                                            "endCursor": end_cursor,
                                        }},
                                    }},
                                }}
                            }}
                        }}
                    }}
                    sys.stdout.write(
                        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\\n"
                    )
                    raise SystemExit(0)
                if method != "GET":
                    raise SystemExit(98)

                if scenario == "rest-nonzero" and path.endswith("/branches/main/protection"):
                    print("fixture diagnostic", file=sys.stderr)
                    raise SystemExit(7)
                if scenario in {
                    "resistant-descendant-normal",
                    "resistant-descendant-interrupt",
                } and path.endswith("/pulls/286"):
                    import signal
                    import time

                    leader_pid = os.getpid()
                    descendant_pid = os.fork()
                    if descendant_pid == 0:
                        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set())
                        dispositions = {{
                            str(int(signum)): (
                                int(signal.getsignal(signum))
                                if isinstance(signal.getsignal(signum), int)
                                else "callable"
                            )
                            for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
                        }}
                        signal.signal(signal.SIGTERM, signal.SIG_IGN)
                        child_ready_path.write_text(
                            json.dumps(
                                {{
                                    "blocked": sorted(int(value) for value in blocked),
                                    "dispositions": dispositions,
                                    "leader_pid": leader_pid,
                                    "pgid": os.getpgrp(),
                                    "pid": os.getpid(),
                                }},
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            + "\\n",
                            encoding="utf-8",
                        )
                        os.close(1)
                        os.close(2)
                        while True:
                            time.sleep(60)
                    deadline = time.monotonic() + 2
                    while not child_ready_path.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if not child_ready_path.exists():
                        raise SystemExit(88)
                    if scenario == "resistant-descendant-normal":
                        raise SystemExit(0)
                    time.sleep(60)
                if scenario == "hang" and path.endswith("/pulls/286"):
                    import time
                    child_ready_path.write_text(
                        json.dumps(
                            {{"pid": os.getpid(), "state": "blocking"}},
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\\n",
                        encoding="utf-8",
                    )
                    time.sleep(60)
                if scenario == "stdout-overflow" and path.endswith("/pulls/286"):
                    sys.stdout.write("x" * 4_194_305)
                    raise SystemExit(0)

                prefix = "repos/nisavid/dotfiles"
                mapping = {{
                    f"{{prefix}}/pulls/286": fixture["pull"],
                    f"{{prefix}}/git/ref/heads/main": fixture["main_ref"],
                    f"{{prefix}}/git/ref/pull/286/head": fixture["pull_head_ref"],
                    f"{{prefix}}/pulls/286/requested_reviewers": fixture["requested_reviewers"],
                    f"{{prefix}}/branches/main/protection": fixture["protection"],
                }}
                paginated = {{
                    f"{{prefix}}/pulls/286/commits": fixture["commits"],
                    f"{{prefix}}/pulls/286/reviews": fixture["reviews"],
                    f"{{prefix}}/rules/branches/main": fixture["effective_rules"],
                    f"{{prefix}}/rulesets": fixture["rulesets"],
                }}
                if path == f"{{prefix}}/commits/{HEAD_COMMIT}/check-runs":
                    value = fixture["check_runs"] if page == 1 else {{
                        "total_count": fixture["check_runs"]["total_count"],
                        "check_runs": [],
                    }}
                elif path in paginated:
                    start = (page - 1) * 100
                    value = paginated[path][start : start + 100]
                elif path in mapping:
                    value = mapping[path]
                else:
                    print("unexpected endpoint", file=sys.stderr)
                    raise SystemExit(93)
                if scenario == "malformed-json" and path.endswith("/pulls/286/reviews"):
                    sys.stdout.write("{{")
                    raise SystemExit(0)
                if path.endswith("/check-runs") and page == 1:
                    admission = next(
                        run
                        for run in value["check_runs"]
                        if run["name"] == {EXCEPTION_CONTEXT!r}
                    )
                    if scenario == "unanimous-required-repeats":
                        for identifier in (101, 102):
                            repeated = json.loads(json.dumps(admission))
                            repeated["id"] = identifier
                            value["check_runs"].append(repeated)
                    if scenario == "mixed-required-repeats":
                        repeated = json.loads(json.dumps(admission))
                        repeated["id"] = 101
                        value["check_runs"].append(repeated)
                        conflicting = json.loads(json.dumps(admission))
                        conflicting["id"] = 102
                        conflicting["conclusion"] = "success"
                        value["check_runs"].append(conflicting)
                    if scenario == "tied-conflicting-required-repeats":
                        admission["completed_at"] = "2026-09-16T12:00:00Z"
                        conflicting = json.loads(json.dumps(admission))
                        conflicting["id"] = 101
                        conflicting["conclusion"] = "success"
                        value["check_runs"].append(conflicting)
                    if scenario == "foreign-app-required-repeat":
                        foreign = json.loads(json.dumps(admission))
                        foreign["id"] = 101
                        foreign["app"]["id"] += 1
                        value["check_runs"].append(foreign)
                    if scenario == "duplicate-check-run-id":
                        value["check_runs"].append(json.loads(json.dumps(admission)))
                    if scenario == "pending-required-repeat":
                        pending = json.loads(json.dumps(admission))
                        pending["id"] = 101
                        pending["status"] = "in_progress"
                        pending["conclusion"] = None
                        value["check_runs"].append(pending)
                    if scenario in {{"failed-unrelated-run", "pending-unrelated-run"}}:
                        unrelated = {{
                            "id": 101,
                            "name": "Optional fixture check",
                            "head_sha": {HEAD_COMMIT!r},
                            "status": "completed",
                            "conclusion": "failure",
                            "app": {{"id": 999999}},
                        }}
                        if scenario == "pending-unrelated-run":
                            unrelated["status"] = "queued"
                            unrelated["conclusion"] = None
                        value["check_runs"].append(unrelated)
                    value["total_count"] = len(value["check_runs"])
                if scenario == "incomplete-checks" and path.endswith("/check-runs"):
                    value["total_count"] += 1
                if scenario == "app-id-mismatch" and path.endswith("/check-runs"):
                    value["check_runs"][0]["app"]["id"] += 1
                if scenario == "trusted-check-success" and path.endswith("/check-runs"):
                    for run in value["check_runs"]:
                        if run["name"] == {EXCEPTION_CONTEXT!r}:
                            run["conclusion"] = "success"
                if scenario == "protection-drift" and path.endswith("/branches/main/protection"):
                    value["enforce_admins"]["enabled"] = False
                if (
                    scenario == "stale-between-passes"
                    and path.endswith("/git/ref/heads/main")
                    and counters[path] == 2
                ):
                    value["object"]["sha"] = "d" * 40
                if scenario == "rest-stderr":
                    print("fixture warning", file=sys.stderr)
                sys.stdout.write(
                    json.dumps(value, sort_keys=True, separators=(",", ":")) + "\\n"
                )
                """),
            encoding="utf-8",
        )
        fake.chmod(0o700)

    def _request_value(self) -> dict[str, object]:
        return {
            "schema": "issue286-recovery-preimage-request/v1",
            "repository": "nisavid/dotfiles",
            "branch": "main",
            "pull_request_number": 286,
            "base_commit": BASE_COMMIT,
            "head_commit": HEAD_COMMIT,
            "reviewed_source_commit": REVIEWED_SOURCE_COMMIT,
            "required_checks": REQUIRED_CHECKS,
            "expected_protection": self._protection(),
            "expected_effective_rules": [],
            "expected_rulesets": [],
        }

    def _write_request(self) -> None:
        self.request.write_bytes(_json_bytes(self._request_value()))
        self.request.chmod(0o600)

    def _set_scenario(self, scenario: str) -> None:
        self.control.write_bytes(_json_bytes({"scenario": scenario}))

    def _environment(self) -> dict[str, str]:
        environment = {
            "PATH": f"{self.bin}{os.pathsep}{self.support_bin}",
            "LC_ALL": "C",
        }
        for credential_field in ("GH_" + "TOKEN", "GITHUB_" + "TOKEN"):
            environment[credential_field] = "disposable-token-must-not-reach-the-child"
        return environment

    def _command(self, state: Path | None = None) -> list[str]:
        return [
            os.fspath(self.python_launcher),
            "-I",
            "-B",
            "-S",
            os.fspath(COLLECTOR),
            "--request",
            os.fspath(self.request),
            "--state-directory",
            os.fspath(self.state if state is None else state),
        ]

    def _run(self, state: Path | None = None) -> subprocess.CompletedProcess[bytes]:
        old_umask = os.umask(0o022)
        try:
            return subprocess.run(
                self._command(state),
                check=False,
                capture_output=True,
                env=self._environment(),
                timeout=20,
            )
        finally:
            os.umask(old_umask)

    def _run_with_collector_fault(
        self, fault: str
    ) -> subprocess.CompletedProcess[bytes]:
        harness = self.private / f"collector-{fault}-fault.py"
        harness.write_text(
            textwrap.dedent(f"""\
                import errno
                import os
                import runpy
                import signal
                import subprocess

                namespace = runpy.run_path({os.fspath(COLLECTOR)!r}, run_name="collector_fault_target")
                real_popen = namespace["subprocess"].Popen
                real_mkdir = namespace["os"].mkdir
                real_killpg = namespace["os"].killpg
                real_rename = namespace["os"].rename
                created = []
                fired = False

                def faulting_popen(*args, **kwargs):
                    process = real_popen(*args, **kwargs)
                    created.append(process)
                    os.kill(os.getpid(), signal.SIGTERM)
                    return process

                def faulting_mkdir(path, mode=0o777, *, dir_fd=None):
                    global fired
                    result = real_mkdir(path, mode, dir_fd=dir_fd)
                    if not fired and dir_fd is not None and os.fspath(path) == {self.state.name!r}:
                        fired = True
                        os.kill(os.getpid(), signal.SIGTERM)
                    return result

                def uncertain_killpg(pgid, signum):
                    if signum == 0:
                        raise PermissionError(errno.EPERM, "synthetic uncertain group probe")
                    return real_killpg(pgid, signum)

                def signaling_rename(*args, **kwargs):
                    if fault == "rename-signal-failure":
                        os.kill(os.getpid(), signal.SIGTERM)
                        raise OSError(errno.EIO, "synthetic ready rename failure")
                    result = real_rename(*args, **kwargs)
                    os.kill(os.getpid(), signal.SIGTERM)
                    return result

                fault = {fault!r}
                if fault in {{"popen-signal", "popen-signal-unverified"}}:
                    namespace["subprocess"].Popen = faulting_popen
                elif fault == "mkdir-signal":
                    namespace["os"].mkdir = faulting_mkdir
                elif fault in {{"rename-signal-success", "rename-signal-failure"}}:
                    namespace["os"].rename = signaling_rename
                else:
                    raise AssertionError(fault)
                if fault == "popen-signal-unverified":
                    namespace["os"].killpg = uncertain_killpg

                try:
                    status = namespace["main"]([
                        "--request", {os.fspath(self.request)!r},
                        "--state-directory", {os.fspath(self.state)!r},
                    ])
                finally:
                    namespace["subprocess"].Popen = real_popen
                    namespace["os"].mkdir = real_mkdir
                    namespace["os"].killpg = real_killpg
                    namespace["os"].rename = real_rename
                    for process in created:
                        if process.poll() is None:
                            try:
                                real_killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            process.wait(timeout=2)
                raise SystemExit(status)
                """),
            encoding="utf-8",
        )
        harness.chmod(0o700)
        return subprocess.run(
            [os.fspath(self.python_launcher), "-I", "-B", "-S", os.fspath(harness)],
            capture_output=True,
            check=False,
            env=self._environment(),
            timeout=10,
        )

    def _wait_for_child_record(self) -> dict[str, object]:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                value = json.loads(self.child_ready.read_bytes())
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.01)
                continue
            if isinstance(value, dict):
                return value
            time.sleep(0.01)
        self.fail("fake GitHub descendant never published its process record")

    def _assert_process_and_group_absent(self, pid: int, pgid: int) -> None:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            pid_absent = False
            group_absent = False
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pid_absent = True
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                group_absent = True
            if pid_absent and group_absent:
                return
            time.sleep(0.02)
        self.fail(f"process group {pgid} or descendant {pid} survived retirement")

    @staticmethod
    def _force_process_group_cleanup(pgid: int) -> None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.02)

    def _write_multi_page_commits(
        self, *, record_padding: int, tail_padding: int
    ) -> None:
        fixture = self._fixture_value()
        commits = [
            {"sha": f"{identifier:040x}", "padding": "x" * record_padding}
            for identifier in range(1, 100)
        ]
        commits.extend(
            [
                {"sha": REVIEWED_SOURCE_COMMIT, "padding": "x" * record_padding},
                {
                    "sha": HEAD_COMMIT,
                    "padding": "x" * record_padding,
                    "tail_padding": "x" * tail_padding,
                },
            ]
        )
        fixture["pull"]["commits"] = len(commits)
        fixture["commits"] = commits
        self.fixture.write_bytes(_json_bytes(fixture))

    @staticmethod
    def _observations_path(state: Path) -> Path:
        ready = json.loads((state / "ready.json").read_bytes())
        return state / ready["payloads"]["observations"]["path"]

    def _calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def _assert_read_only_calls(self) -> None:
        for arguments in self._calls():
            method = arguments[arguments.index("--method") + 1]
            if method == "POST":
                self.assertEqual(arguments[-1], "graphql")
                self.assertEqual(arguments[-3:-1], ["--input", "-"])
            else:
                self.assertEqual(method, "GET")
                self.assertNotEqual(arguments[-1], "graphql")

    def _assert_failed_without_ready(self, scenario: str) -> None:
        self._set_scenario(scenario)
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation failed\n")
        self.assertFalse((self.state / "ready.json").exists())
        self._assert_read_only_calls()

    def test_harness_uses_a_physical_root_and_closed_support_path(self) -> None:
        self.assertEqual(self.private, self.private.resolve(strict=True))
        current = Path("/")
        for component in self.private.parts[1:]:
            current /= component
            self.assertFalse(stat.S_ISLNK(os.lstat(current).st_mode), current)

        environment = self._environment()
        self.assertEqual(
            environment["PATH"].split(os.pathsep),
            [os.fspath(self.bin), os.fspath(self.support_bin)],
        )
        self.assertNotEqual(self.python_launcher.parent, Path(sys.executable).parent)
        self.assertEqual(
            shutil.which("gh", path=environment["PATH"]), os.fspath(self.bin / "gh")
        )
        self.assertIsNone(shutil.which("pass-cli", path=environment["PATH"]))
        self.assertEqual(
            (self.bin / "gh").read_text(encoding="utf-8").splitlines()[0],
            f"#!{self.python_launcher}",
        )
        support_names = {path.name for path in self.support_bin.iterdir()}
        self.assertEqual(
            support_names,
            {
                "python3",
                *REQUIRED_SUPPORT_TOOLS,
                *set(self.support_tools) & set(HASH_SUPPORT_TOOLS),
            },
        )

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self._assert_read_only_calls()

    def _extract_recovery_state_machine(self) -> Path:
        lines = RECOVERY_RUNBOOK.read_text(encoding="utf-8").splitlines()
        heading = lines.index("### Apply one exception, merge, and restore")
        fence = lines.index("```zsh", heading)
        end = lines.index("```", fence + 1)
        target = self.private / "recovery-state-machine.zsh"
        target.write_text("\n".join(lines[fence + 1 : end]) + "\n", encoding="utf-8")
        target.chmod(0o700)
        return target

    def _extract_recovery_preimage_launcher(self) -> Path:
        lines = RECOVERY_RUNBOOK.read_text(encoding="utf-8").splitlines()
        heading = lines.index("### Revalidate the administrative preimage")
        end_heading = lines.index("### Apply one exception, merge, and restore")
        blocks: list[str] = []
        index = heading + 1
        while index < end_heading:
            if lines[index] != "```zsh":
                index += 1
                continue
            fence_end = lines.index("```", index + 1, end_heading)
            blocks.append("\n".join(lines[index + 1 : fence_end]))
            index = fence_end + 1
        self.assertEqual(len(blocks), 1)
        target = self.private / "recovery-preimage-launcher.zsh"
        target.write_text("\n".join(blocks) + "\n", encoding="utf-8")
        target.chmod(0o700)
        return target

    def _write_private_json(self, path: Path, value: object) -> None:
        path.write_bytes(_json_bytes(value))
        path.chmod(0o600)

    def _prepare_recovery_mutation_state(self) -> Path:
        mutation = self.private / "mutation"
        mutation.mkdir(mode=0o700)
        preimage = self._protection()
        exception = copy.deepcopy(preimage)
        status = exception["required_status_checks"]
        status["contexts"] = [
            value for value in status["contexts"] if value != EXCEPTION_CONTEXT
        ]
        status["checks"] = [
            value for value in status["checks"] if value["context"] != EXCEPTION_CONTEXT
        ]
        self._write_private_json(mutation / "preimage.json", preimage)
        self._write_private_json(mutation / "exception.json", exception)
        self._write_private_json(mutation / "protection.json", preimage)
        self._write_private_json(
            mutation / "pull.json",
            {
                "state": "open",
                "merged": False,
                "merge_commit_sha": None,
                "base": {"ref": "main", "sha": BASE_COMMIT},
                "head": {"sha": HEAD_COMMIT},
            },
        )
        (mutation / "main.sha").write_text(BASE_COMMIT + "\n", encoding="ascii")
        (mutation / "main.sha").chmod(0o600)
        (mutation / "calls.log").write_bytes(b"")
        (mutation / "calls.log").chmod(0o600)
        return mutation

    def _install_recovery_gh_dispatch(self) -> None:
        collector_gh = self.bin / "collector-gh"
        (self.bin / "gh").rename(collector_gh)
        dispatcher = self.bin / "gh"
        dispatcher.write_text(
            f"#!{self.zsh}\n"
            'for argument in "$@"; do\n'
            "  if [[ $argument == --hostname ]]; then\n"
            f'    exec {shlex.quote(os.fspath(collector_gh))} "$@"\n'
            "  fi\n"
            "done\n"
            f"exec {shlex.quote(os.fspath(self.zsh))} "
            f'{shlex.quote(os.fspath(RECOVERY_GH_FIXTURE))} "$@"\n',
            encoding="utf-8",
        )
        dispatcher.chmod(0o700)

    def _install_signaling_cmp(self) -> None:
        wrapper = self.support_bin / "cmp"
        wrapper.unlink()
        wrapper.write_text(
            f"#!{self.zsh}\n"
            'if [[ "$*" == *main-protection.restored.*.canonical.json* ]]; then\n'
            '  kill -TERM "$PPID"\n'
            "  sleep 0.1\n"
            '  kill -INT "$PPID"\n'
            "  sleep 0.1\n"
            '  kill -HUP "$PPID"\n'
            "fi\n"
            f"exec {shlex.quote(os.fspath(self.support_tools['cmp']))} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o700)

    def _run_recovery_procedure(
        self, scenario: str, *, rejected_gate: str | None = None
    ) -> tuple[subprocess.CompletedProcess[bytes], Path]:
        staged_collector = self.private / "prepare-age-admission-recovery-preimage"
        staged_collector.write_bytes(COLLECTOR.read_bytes())
        staged_collector.chmod(0o600)
        collector_sha = _sha256(staged_collector.read_bytes())
        procedure_private = self.private / "procedure-private"
        procedure_private.mkdir(mode=0o700)

        launcher = self._extract_recovery_preimage_launcher()
        state_machine = self._extract_recovery_state_machine()
        interstitial = ""
        if rejected_gate == "malformed-ready-manifest":
            interstitial = textwrap.dedent("""\
                jq -cS 'del(.artifacts[0])' \
                  "$RECOVERY_STATE_DIRECTORY/ready.json" \
                  >"$RECOVERY_STATE_DIRECTORY/ready.malformed.json"
                mv "$RECOVERY_STATE_DIRECTORY/ready.malformed.json" \
                  "$RECOVERY_STATE_DIRECTORY/ready.json"
                RECOVERY_PREIMAGE_READY_SHA256=$(file_sha256 \
                  "$RECOVERY_STATE_DIRECTORY/ready.json")
                """)
        elif rejected_gate == "stale-fresh-replay":
            stale_control = self.private / "stale-control.json"
            empty_counter = self.private / "empty-counter.json"
            self._write_private_json(
                stale_control, {"scenario": "stale-between-passes"}
            )
            self._write_private_json(empty_counter, {})
            interstitial = (
                f"cp {shlex.quote(os.fspath(stale_control))} "
                f"{shlex.quote(os.fspath(self.control))}\n"
                f"cp {shlex.quote(os.fspath(empty_counter))} "
                f"{shlex.quote(os.fspath(self.counter))}\n"
            )
        elif rejected_gate is not None:
            raise AssertionError(f"unknown rejected gate: {rejected_gate}")

        mutation = self._prepare_recovery_mutation_state()
        self._install_recovery_gh_dispatch()
        if scenario == "restore-compare-repeated-signals":
            self._install_signaling_cmp()
        procedure = self.private / "recovery-procedure.zsh"
        procedure.write_text(
            launcher.read_text(encoding="utf-8")
            + interstitial
            + state_machine.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        procedure.chmod(0o700)
        environment = self._environment()
        environment.update(
            {
                "FAKE_GH_STATE_DIR": os.fspath(mutation),
                "FAKE_GH_SCENARIO": scenario,
                "RECOVERY_PREIMAGE_PRIVATE_PARENT": os.fspath(procedure_private),
                "RECOVERY_PREIMAGE_COLLECTOR": os.fspath(staged_collector),
                "RECOVERY_PREIMAGE_COLLECTOR_SHA256": collector_sha,
                "RECOVERY_FRESH_STATE_DIRECTORY": os.fspath(
                    procedure_private / "fresh"
                ),
                "RECOVERY_REVIEWED_SOURCE": REVIEWED_SOURCE_COMMIT,
                "RECOVERY_PR_NUMBER": "286",
                "RECOVERY_BASE": BASE_COMMIT,
                "RECOVERY_HEAD": HEAD_COMMIT,
            }
        )
        result = subprocess.run(
            [os.fspath(self.zsh), os.fspath(procedure)],
            capture_output=True,
            check=False,
            env=environment,
            timeout=30,
        )
        return result, mutation

    def _recovery_merge_attempts(self, mutation: Path) -> int:
        calls = (mutation / "calls.log").read_text(encoding="utf-8").splitlines()
        return sum(
            line.startswith("api --method PUT repos/nisavid/dotfiles/pulls/286/merge")
            for line in calls
        )

    @staticmethod
    def _recovery_restore_attempts(mutation: Path) -> int:
        calls = (mutation / "calls.log").read_text(encoding="utf-8").splitlines()
        return sum("required-checks.restore.json" in line for line in calls)

    def _assert_recovery_outcome(
        self,
        scenario: str,
        expected_status: str | int,
        expected_protection: str,
        expected_merge_attempts: int,
        expected_restore_attempts: int,
    ) -> None:
        result, mutation = self._run_recovery_procedure(scenario)

        if expected_status == "zero":
            self.assertEqual(
                result.returncode, 0, result.stderr.decode(errors="replace")
            )
        elif expected_status == "nonzero":
            self.assertNotEqual(
                result.returncode,
                0,
                (result.stdout, result.stderr),
            )
        else:
            self.assertEqual(
                result.returncode,
                expected_status,
                result.stderr.decode(errors="replace"),
            )
        self.assertEqual(
            (mutation / "protection.json").read_bytes(),
            (mutation / f"{expected_protection}.json").read_bytes(),
        )
        self.assertEqual(
            self._recovery_merge_attempts(mutation), expected_merge_attempts
        )
        self.assertEqual(
            self._recovery_restore_attempts(mutation), expected_restore_attempts
        )

    def _assert_ready_gate_rejected(self, rejected_gate: str) -> None:
        result, mutation = self._run_recovery_procedure(
            "success", rejected_gate=rejected_gate
        )

        self.assertNotEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertEqual((mutation / "calls.log").read_bytes(), b"")
        self.assertEqual(
            (mutation / "protection.json").read_bytes(),
            (mutation / "preimage.json").read_bytes(),
        )
        self.assertEqual(self._recovery_merge_attempts(mutation), 0)
        self.assertEqual(self._recovery_restore_attempts(mutation), 0)

    def test_preimage_launcher_rejects_an_unverified_collector_before_execution(
        self,
    ) -> None:
        private_parent = self.private / "launcher-private"
        private_parent.mkdir(mode=0o700)
        marker = self.private / "unverified-collector-ran"
        staged_collector = self.private / "unverified-collector"
        staged_collector.write_text(
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['UNVERIFIED_COLLECTOR_MARKER']).write_bytes(b'ran\\n')\n"
            "print('recovery preimage ready')\n",
            encoding="utf-8",
        )
        staged_collector.chmod(0o600)
        launcher = self._extract_recovery_preimage_launcher()
        environment = self._environment()
        environment.update(
            {
                "RECOVERY_PR_NUMBER": "286",
                "RECOVERY_BASE": BASE_COMMIT,
                "RECOVERY_HEAD": HEAD_COMMIT,
                "RECOVERY_REVIEWED_SOURCE": REVIEWED_SOURCE_COMMIT,
                "RECOVERY_PREIMAGE_PRIVATE_PARENT": os.fspath(private_parent),
                "RECOVERY_PREIMAGE_COLLECTOR": os.fspath(staged_collector),
                "RECOVERY_PREIMAGE_COLLECTOR_SHA256": "0" * 64,
                "UNVERIFIED_COLLECTOR_MARKER": os.fspath(marker),
            }
        )

        result = subprocess.run(
            [os.fspath(self.zsh), os.fspath(launcher)],
            capture_output=True,
            check=False,
            env=environment,
            timeout=10,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertFalse((private_parent / "request.json").exists())
        self.assertFalse((private_parent / "initial").exists())

    def test_recovery_success_restores_protection_after_one_merge_attempt(
        self,
    ) -> None:
        self._assert_recovery_outcome("success", "zero", "preimage", 1, 1)

    def test_ambiguous_exception_request_restores_without_attempting_merge(
        self,
    ) -> None:
        self._assert_recovery_outcome(
            "exception-patch-ambiguous", "nonzero", "preimage", 0, 1
        )

    def test_wrong_applied_exception_restores_without_attempting_merge(self) -> None:
        self._assert_recovery_outcome("exception-wrong", "nonzero", "preimage", 0, 1)

    def test_ambiguous_merge_request_observes_merge_and_restores(self) -> None:
        self._assert_recovery_outcome("merge-ambiguous", "zero", "preimage", 1, 1)

    def test_merge_api_error_leaves_pull_unmerged_and_restores(self) -> None:
        self._assert_recovery_outcome("merge-error", "nonzero", "preimage", 1, 1)

    def test_explicit_merge_rejection_leaves_pull_unmerged_and_restores(self) -> None:
        self._assert_recovery_outcome("merge-rejected", "nonzero", "preimage", 1, 1)

    def test_ambiguous_restoration_accepts_observed_restored_state(self) -> None:
        self._assert_recovery_outcome("restore-ambiguous", "zero", "preimage", 1, 1)

    def test_unavailable_restoration_reports_125_and_leaves_exception(self) -> None:
        self._assert_recovery_outcome("restore-fails", 125, "exception", 1, 2)

    def test_exit_retry_restores_after_the_explicit_restore_attempt_fails(
        self,
    ) -> None:
        self._assert_recovery_outcome("restore-fails-once", 125, "preimage", 1, 2)

    def test_interruption_during_exception_request_restores_without_merge(
        self,
    ) -> None:
        self._assert_recovery_outcome("interrupt-patch", 143, "preimage", 0, 1)

    def test_interruption_during_merge_restores_after_one_attempt(self) -> None:
        self._assert_recovery_outcome("interrupt-merge", 143, "preimage", 1, 1)

    def test_repeated_signals_during_explicit_restore_keep_term_and_one_attempt(
        self,
    ) -> None:
        self._assert_recovery_outcome("restore-repeated-signals", 143, "preimage", 1, 1)

    def test_repeated_signals_during_restore_read_keep_term_and_one_attempt(
        self,
    ) -> None:
        self._assert_recovery_outcome(
            "restore-read-repeated-signals", 143, "preimage", 1, 1
        )

    def test_repeated_signals_during_restore_compare_keep_term_and_one_attempt(
        self,
    ) -> None:
        self._assert_recovery_outcome(
            "restore-compare-repeated-signals", 143, "preimage", 1, 1
        )

    def test_repeated_signals_during_exit_restore_do_not_reenter_finalizer(
        self,
    ) -> None:
        self._assert_recovery_outcome(
            "finalizer-repeated-signals", 143, "preimage", 0, 1
        )

    def test_exit_restore_child_does_not_inherit_ignored_term(self) -> None:
        self._assert_recovery_outcome(
            "finalizer-child-self-term", 125, "exception", 0, 1
        )

    def test_malformed_ready_manifest_is_rejected_before_mutation(self) -> None:
        self._assert_ready_gate_rejected("malformed-ready-manifest")

    def test_stale_fresh_replay_is_rejected_before_mutation(self) -> None:
        self._assert_ready_gate_rejected("stale-fresh-replay")

    def test_noncanonical_request_fails_before_state_creation(self) -> None:
        self.request.write_text(
            json.dumps(self._request_value(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.request.chmod(0o600)

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation failed\n")
        self.assertFalse(self.state.exists())
        self.assertFalse(self.calls.exists())

    def test_symlink_request_fails_before_state_creation(self) -> None:
        target = self.private / "request-target.json"
        self.request.rename(target)
        self.request.symlink_to(target)

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.calls.exists())

    def test_loose_request_mode_fails_before_state_creation(self) -> None:
        self.request.chmod(0o644)

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.calls.exists())

    def test_existing_state_directory_fails_before_github_read(self) -> None:
        self.state.mkdir(mode=0o700)

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.state / "ready.json").exists())
        self.assertFalse(self.calls.exists())

    def test_resolved_threads_are_fully_paginated_even_when_one_is_outdated(
        self,
    ) -> None:
        self._set_scenario("graphql-pagination")

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        ready = json.loads((self.state / "ready.json").read_bytes())
        observations = json.loads(
            (self.state / ready["payloads"]["observations"]["path"]).read_bytes()
        )
        self.assertEqual(
            observations["review_threads"],
            [
                {"id": "PRRT_resolved", "isOutdated": False, "isResolved": True},
                {
                    "id": "PRRT_resolved_outdated",
                    "isOutdated": True,
                    "isResolved": True,
                },
            ],
        )
        inputs = [
            json.loads(line) for line in self.graphql_inputs.read_text().splitlines()
        ]
        self.assertEqual(
            [item["variables"]["threadsCursor"] for item in inputs],
            [None, "fixture-page-one", None, "fixture-page-one"],
        )
        self._assert_read_only_calls()

    def test_unresolved_outdated_thread_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("graphql-unresolved-outdated")

    def test_graphql_errors_leave_no_ready_file(self) -> None:
        self._assert_failed_without_ready("graphql-errors")

    def test_malformed_capture_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("malformed-json")

    def test_incomplete_check_pagination_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("incomplete-checks")

    def test_unanimous_repeated_required_runs_are_retained(self) -> None:
        self._set_scenario("unanimous-required-repeats")

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        ready = json.loads((self.state / "ready.json").read_bytes())
        observations = json.loads(
            (self.state / ready["payloads"]["observations"]["path"]).read_bytes()
        )
        matches = [
            run
            for run in observations["check_runs"]["check_runs"]
            if run["name"] == EXCEPTION_CONTEXT and run["app"]["id"] == 15368
        ]
        self.assertEqual([run["id"] for run in matches], [5, 101, 102])
        self.assertTrue(all(run["status"] == "completed" for run in matches))
        self.assertTrue(all(run["conclusion"] == "failure" for run in matches))
        self._assert_read_only_calls()

    def test_large_opaque_github_ids_are_retained(self) -> None:
        fixture = self._fixture_value()
        fixture["pull"]["user"]["id"] = FIRST_ID_OVER_SIGNED_32_BIT
        fixture["reviews"][0]["id"] = FIRST_ID_OVER_SIGNED_32_BIT + 1
        fixture["reviews"][0]["user"]["id"] = FIRST_ID_OVER_SIGNED_32_BIT + 2
        fixture["check_runs"]["check_runs"][0]["id"] = PUBLIC_CHECK_RUN_ID
        self.fixture.write_bytes(_json_bytes(fixture))

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        ready = json.loads((self.state / "ready.json").read_bytes())
        observations = json.loads(
            (self.state / ready["payloads"]["observations"]["path"]).read_bytes()
        )
        self.assertEqual(
            observations["pull"]["user"]["id"], FIRST_ID_OVER_SIGNED_32_BIT
        )
        self.assertEqual(
            observations["reviews"][0]["id"], FIRST_ID_OVER_SIGNED_32_BIT + 1
        )
        self.assertEqual(
            observations["reviews"][0]["user"]["id"],
            FIRST_ID_OVER_SIGNED_32_BIT + 2,
        )
        self.assertIn(
            PUBLIC_CHECK_RUN_ID,
            {run["id"] for run in observations["check_runs"]["check_runs"]},
        )
        self._assert_read_only_calls()

    def test_mixed_repeated_required_conclusions_leave_no_ready_file(self) -> None:
        self._assert_failed_without_ready("mixed-required-repeats")

    def test_tied_conflicting_required_runs_leave_no_ready_file(self) -> None:
        self._assert_failed_without_ready("tied-conflicting-required-repeats")

    def test_foreign_app_required_context_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("foreign-app-required-repeat")

    def test_duplicate_check_run_ids_leave_no_ready_file(self) -> None:
        self._assert_failed_without_ready("duplicate-check-run-id")

    def test_pending_required_run_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("pending-required-repeat")

    def test_failed_unrelated_run_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("failed-unrelated-run")

    def test_pending_unrelated_run_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("pending-unrelated-run")

    def test_required_check_app_mismatch_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("app-id-mismatch")

    def test_successful_old_key_check_is_not_a_prepared_exception(self) -> None:
        self._assert_failed_without_ready("trusted-check-success")

    def test_unrelated_protection_drift_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("protection-drift")

    def test_stale_evidence_between_observations_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("stale-between-passes")

    def test_nonzero_github_read_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("rest-nonzero")

    def test_warning_bearing_github_read_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("rest-stderr")

    def test_oversized_github_capture_is_bounded_and_leaves_no_ready_file(self) -> None:
        self._set_scenario("stdout-overflow")

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.state / "ready.json").exists())
        status = next((self.state / "captures").glob("*.status.json"))
        self.assertEqual(json.loads(status.read_bytes())["outcome"], "capture-overflow")
        capture = next((self.state / "captures").glob("*.stdout.json"))
        self.assertEqual(capture.stat().st_size, 4_194_304)
        self._assert_read_only_calls()

    def test_multi_page_payload_accepts_its_limit_and_rejects_one_more_byte(
        self,
    ) -> None:
        calibration_state = self.private / "calibration"
        self._write_multi_page_commits(record_padding=0, tail_padding=0)
        calibration = self._run(calibration_state)
        self.assertEqual(
            calibration.returncode,
            0,
            calibration.stderr.decode("utf-8", "replace"),
        )
        baseline_size = self._observations_path(calibration_state).stat().st_size
        padding_bytes = PAYLOAD_ARTIFACT_MAX_BYTES - baseline_size
        self.assertGreater(padding_bytes, 101)
        record_padding, tail_padding = divmod(padding_bytes, 101)

        boundary_state = self.private / "payload-boundary"
        self._write_multi_page_commits(
            record_padding=record_padding, tail_padding=tail_padding
        )
        boundary = self._run(boundary_state)
        self.assertEqual(
            boundary.returncode, 0, boundary.stderr.decode("utf-8", "replace")
        )
        self.assertEqual(
            self._observations_path(boundary_state).stat().st_size,
            PAYLOAD_ARTIFACT_MAX_BYTES,
        )

        overflow_state = self.private / "payload-overflow"
        self._write_multi_page_commits(
            record_padding=record_padding, tail_padding=tail_padding + 1
        )
        overflow = self._run(overflow_state)
        self.assertEqual(overflow.returncode, 1)
        self.assertEqual(overflow.stdout, b"")
        self.assertEqual(overflow.stderr, b"recovery preimage preparation failed\n")
        self.assertFalse((overflow_state / "ready.json").exists())
        self.assertFalse((overflow_state / "payloads/observations.json").exists())
        self._assert_read_only_calls()

    def test_caught_signal_records_interruption_and_leaves_no_ready_file(self) -> None:
        self._set_scenario("hang")
        process = subprocess.Popen(
            self._command(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._environment(),
        )
        deadline = time.monotonic() + 5
        child_pid: int | None = None
        while time.monotonic() < deadline:
            try:
                ready = json.loads(self.child_ready.read_bytes())
            except (FileNotFoundError, json.JSONDecodeError):
                ready = None
            if (
                isinstance(ready, dict)
                and set(ready) == {"pid", "state"}
                and ready["state"] == "blocking"
                and isinstance(ready["pid"], int)
                and not isinstance(ready["pid"], bool)
                and ready["pid"] > 0
            ):
                try:
                    os.kill(ready["pid"], 0)
                except ProcessLookupError:
                    pass
                else:
                    child_pid = ready["pid"]
                    break
            time.sleep(0.01)
        self.assertIsNotNone(
            child_pid, "fake GitHub child never reached its blocking state"
        )
        assert child_pid is not None

        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)

        self.assertIsNotNone(process.poll(), "collector did not retire")
        child_deadline = time.monotonic() + 2
        while time.monotonic() < child_deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            self.fail("fake GitHub child survived collector retirement")
        self.assertEqual(process.returncode, 128 + signal.SIGTERM)
        self.assertEqual(stdout, b"")
        self.assertEqual(stderr, b"recovery preimage preparation interrupted\n")
        self.assertFalse((self.state / "ready.json").exists())
        statuses = sorted((self.state / "captures").glob("*.status.json"))
        self.assertEqual(len(statuses), 1)
        self.assertGreater(statuses[0].stat().st_size, 0)
        self.assertEqual(
            json.loads(statuses[0].read_bytes()),
            {
                "caught_signal": signal.SIGTERM,
                "method": "GET",
                "outcome": "interrupted",
            },
        )
        self._assert_read_only_calls()

    def test_signal_during_process_spawn_is_honored_after_registration(self) -> None:
        self._set_scenario("hang")

        result = self._run_with_collector_fault("popen-signal")

        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation interrupted\n")
        self.assertFalse((self.state / "ready.json").exists())
        status = next((self.state / "captures").glob("*.status.json"))
        self.assertEqual(
            json.loads(status.read_bytes()),
            {
                "caught_signal": signal.SIGTERM,
                "method": "GET",
                "outcome": "interrupted",
            },
        )

    def test_signal_during_state_mkdir_retains_state_without_publishing(self) -> None:
        result = self._run_with_collector_fault("mkdir-signal")

        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation interrupted\n")
        self.assertTrue(self.state.is_dir())
        self.assertFalse((self.state / "ready.json").exists())
        self.assertFalse(self.calls.exists())

    def test_signal_after_ready_rename_defers_to_the_successful_commit(self) -> None:
        result = self._run_with_collector_fault("rename-signal-success")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"recovery preimage ready\n")
        self.assertEqual(result.stderr, b"")
        self.assertTrue((self.state / "ready.json").is_file())

    def test_failed_ready_rename_restores_signal_delivery_and_publishes_nothing(
        self,
    ) -> None:
        result = self._run_with_collector_fault("rename-signal-failure")

        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation interrupted\n")
        self.assertFalse((self.state / "ready.json").exists())

    def test_uncertain_group_retirement_is_a_retained_failure(self) -> None:
        self._set_scenario("hang")

        result = self._run_with_collector_fault("popen-signal-unverified")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation failed\n")
        self.assertFalse((self.state / "ready.json").exists())
        status = next((self.state / "captures").glob("*.status.json"))
        self.assertEqual(
            json.loads(status.read_bytes()),
            {
                "caught_signal": signal.SIGTERM,
                "method": "GET",
                "outcome": "unverified-retirement",
            },
        )

    def test_normal_leader_exit_with_resistant_descendant_fails_after_retirement(
        self,
    ) -> None:
        self._set_scenario("resistant-descendant-normal")

        result = self._run()
        record = self._wait_for_child_record()

        try:
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(result.stderr, b"recovery preimage preparation failed\n")
            self.assertFalse((self.state / "ready.json").exists())
            self.assertEqual(record["leader_pid"], record["pgid"])
            self.assertNotIn(signal.SIGHUP, record["blocked"])
            self.assertNotIn(signal.SIGINT, record["blocked"])
            self.assertNotIn(signal.SIGTERM, record["blocked"])
            for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
                self.assertNotEqual(
                    record["dispositions"][str(int(signum))], int(signal.SIG_IGN)
                )
            self._assert_process_and_group_absent(
                int(record["pid"]), int(record["pgid"])
            )
        finally:
            self._force_process_group_cleanup(int(record["pgid"]))

    def test_repeated_signals_keep_first_status_and_do_not_extend_retirement(
        self,
    ) -> None:
        self._set_scenario("resistant-descendant-interrupt")
        process = subprocess.Popen(
            self._command(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._environment(),
        )
        record = self._wait_for_child_record()

        started = time.monotonic()
        process.send_signal(signal.SIGTERM)
        time.sleep(0.05)
        process.send_signal(signal.SIGINT)
        process.send_signal(signal.SIGHUP)
        stdout, stderr = process.communicate(timeout=8)
        elapsed = time.monotonic() - started

        try:
            self.assertEqual(process.returncode, 128 + signal.SIGTERM)
            self.assertEqual(stdout, b"")
            self.assertEqual(stderr, b"recovery preimage preparation interrupted\n")
            self.assertLess(elapsed, 6)
            self.assertFalse((self.state / "ready.json").exists())
            status = next((self.state / "captures").glob("*.status.json"))
            self.assertEqual(
                json.loads(status.read_bytes()),
                {
                    "caught_signal": signal.SIGTERM,
                    "method": "GET",
                    "outcome": "interrupted",
                },
            )
            self._assert_process_and_group_absent(
                int(record["pid"]), int(record["pgid"])
            )
        finally:
            self._force_process_group_cleanup(int(record["pgid"]))

    def test_nonpositive_required_app_id_fails_before_state_creation(self) -> None:
        request = self._request_value()
        checks = json.loads(json.dumps(request["required_checks"]))
        checks[0]["app_id"] = 0
        request["required_checks"] = checks
        expected = json.loads(json.dumps(request["expected_protection"]))
        expected["required_status_checks"]["checks"] = checks
        request["expected_protection"] = expected
        self.request.write_bytes(_json_bytes(request))
        self.request.chmod(0o600)

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.calls.exists())

    def test_pull_request_number_outside_graphql_int_fails_before_state_creation(
        self,
    ) -> None:
        request = self._request_value()
        request["pull_request_number"] = FIRST_ID_OVER_SIGNED_32_BIT
        self.request.write_bytes(_json_bytes(request))
        self.request.chmod(0o600)

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.calls.exists())

    def test_success_writes_a_digest_bound_ready_file_last_with_read_only_calls(
        self,
    ) -> None:
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"recovery preimage ready\n")
        self.assertEqual(result.stderr, b"")
        ready_path = self.state / "ready.json"
        ready_bytes = ready_path.read_bytes()
        ready = json.loads(ready_bytes)
        self.assertEqual(
            set(ready),
            {
                "artifacts",
                "binding",
                "collector_sha256",
                "graphql_query_sha256",
                "limits",
                "observations_sha256",
                "outcome",
                "payloads",
                "request_sha256",
                "schema",
            },
        )
        self.assertEqual(
            set(ready["limits"]),
            {
                "capture_stderr_bytes",
                "capture_stdout_bytes",
                "capture_timeout_seconds",
                "capture_total_bytes",
                "max_artifacts",
                "max_pages",
                "page_size",
                "ready_bytes",
                "request_bytes",
                "terminate_grace_seconds",
                "total_timeout_seconds",
            },
        )
        self.assertEqual(ready["schema"], "issue286-recovery-preimage-ready/v1")
        self.assertEqual(ready["outcome"], "ready")
        self.assertEqual(ready["graphql_query_sha256"], GRAPHQL_QUERY_SHA256)
        self.assertEqual(ready["request_sha256"], _sha256(self.request.read_bytes()))
        self.assertEqual(ready["binding"]["base_commit"], BASE_COMMIT)
        self.assertEqual(ready["binding"]["head_commit"], HEAD_COMMIT)
        self.assertEqual(
            ready["binding"]["reviewed_source_commit"], REVIEWED_SOURCE_COMMIT
        )

        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        ready_mtime = ready_path.stat().st_mtime_ns
        artifact_paths: set[str] = set()
        for artifact in ready["artifacts"]:
            relative = artifact["path"]
            self.assertNotIn(relative, artifact_paths)
            artifact_paths.add(relative)
            path = self.state / relative
            data = path.read_bytes()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_uid, os.getuid())
            self.assertEqual(artifact["bytes"], len(data))
            self.assertEqual(artifact["sha256"], _sha256(data))
            self.assertLessEqual(path.stat().st_mtime_ns, ready_mtime)
        self.assertEqual(stat.S_IMODE(ready_path.stat().st_mode), 0o600)
        self.assertEqual(ready_path.stat().st_uid, os.getuid())

        self.assertEqual(
            set(ready["payloads"]),
            {
                "exception_checks",
                "observations",
                "protection_preimage",
                "restore_checks",
            },
        )
        for reference in ready["payloads"].values():
            self.assertIn(reference["path"], artifact_paths)
            self.assertEqual(
                reference["sha256"],
                _sha256((self.state / reference["path"]).read_bytes()),
            )
        restore = json.loads(
            (self.state / ready["payloads"]["restore_checks"]["path"]).read_bytes()
        )
        exception = json.loads(
            (self.state / ready["payloads"]["exception_checks"]["path"]).read_bytes()
        )
        self.assertEqual(len(restore["checks"]), 5)
        self.assertEqual(len(exception["checks"]), 4)
        self.assertNotIn(
            EXCEPTION_CONTEXT, {item["context"] for item in exception["checks"]}
        )

        calls = self._calls()
        self.assertGreaterEqual(len(calls), 20)
        for arguments in calls:
            self.assertEqual(arguments[0], "api")
            method = arguments[arguments.index("--method") + 1]
            if arguments[-1] == "graphql":
                self.assertEqual(method, "POST")
                self.assertEqual(arguments[-3:-1], ["--input", "-"])
            else:
                self.assertEqual(method, "GET")
            self.assertNotIn("--paginate", arguments)
        endpoints = [arguments[-1] for arguments in calls]
        self.assertEqual(endpoints.count("repos/nisavid/dotfiles/pulls/286"), 2)
        self.assertEqual(
            endpoints.count("repos/nisavid/dotfiles/branches/main/protection"), 2
        )
        self.assertEqual(endpoints.count("graphql"), 2)
        self.assertEqual(
            endpoints.count(
                f"repos/nisavid/dotfiles/commits/{HEAD_COMMIT}/check-runs"
                "?filter=latest&per_page=100&page=1"
            ),
            2,
        )
        self.assertEqual(
            endpoints.count(
                "repos/nisavid/dotfiles/rulesets"
                "?includes_parents=true&per_page=100&page=1"
            ),
            2,
        )
        graphql_inputs = [
            json.loads(line) for line in self.graphql_inputs.read_text().splitlines()
        ]
        self.assertEqual(len(graphql_inputs), 2)
        self.assertTrue(all(item["query"] == GRAPHQL_QUERY for item in graphql_inputs))
        self.assertTrue(
            all("mutation" not in item["query"].lower() for item in graphql_inputs)
        )


if __name__ == "__main__":
    unittest.main()
