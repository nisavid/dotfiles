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
CODERABBIT_CONTEXT = "CodeRabbit"
CODERABBIT_APP_ID = 347564
CODERABBIT_STATUS_CREATOR_ID = 136622811
CODERABBIT_STATUS_CREATOR_LOGIN = "coderabbitai[bot]"
REQUIRED_CHECKS = [
    {"context": "check conventional commit compliance", "app_id": 15368},
    {"context": CODERABBIT_CONTEXT, "app_id": CODERABBIT_APP_ID},
    {"context": "zsh deployment portability", "app_id": 15368},
    {"context": EXCEPTION_CONTEXT, "app_id": 15368},
]
REQUIRED_CHECK_SOURCES = [
    {
        "context": "check conventional commit compliance",
        "source": "check-run",
        "app_id": 15368,
    },
    {
        "context": CODERABBIT_CONTEXT,
        "source": "commit-status",
        "creator_id": CODERABBIT_STATUS_CREATOR_ID,
        "creator_login": CODERABBIT_STATUS_CREATOR_LOGIN,
    },
    {"context": "zsh deployment portability", "source": "check-run", "app_id": 15368},
    {"context": EXCEPTION_CONTEXT, "source": "check-run", "app_id": 15368},
]
# CodeRabbit's bot account also submits its reviews; the request pins that role
# separately from the status creator.
TRUSTED_REVIEWERS = [
    {"id": CODERABBIT_STATUS_CREATOR_ID, "login": CODERABBIT_STATUS_CREATOR_LOGIN}
]
RETIRED_REQUIRED_CHECK = {"context": "Greptile Review", "app_id": 867647}
RELEVANT_STATE_DRIFTS = (
    "approval-drift",
    "check-run-identity-drift",
    "pull-discussion-drift",
    "pull-title-drift",
    "repository-setting-drift",
    "status-drift",
    "thread-drift",
)
REQUEST_SCHEMA = "issue286-recovery-preimage-request/v2"
READY_SCHEMA = "issue286-recovery-preimage-ready/v2"
INTERRUPTED_SCHEMA = "issue286-recovery-preimage-interrupted/v1"
PULL_ENDPOINT = "repos/nisavid/dotfiles/pulls/286"
RULESETS_FIRST_PAGE = (
    "repos/nisavid/dotfiles/rulesets?includes_parents=true&per_page=100&page=1"
)
STATUSES_ENDPOINT = f"repos/nisavid/dotfiles/commits/{HEAD_COMMIT}/statuses"
STATUSES_FIRST_PAGE = f"{STATUSES_ENDPOINT}?per_page=100&page=1"
STATUS_URL = f"https://api.github.com/repos/nisavid/dotfiles/statuses/{HEAD_COMMIT}"
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
      reviewDecision
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
    "4ce24d04bdcdf3b7fdf792cc2156d113acaa52250e469728b2d87a8991a87e36"
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


def _github_account(
    login: str,
    identifier: int,
    node_id: str,
    avatar_url: str,
    html_url: str,
    kind: str,
) -> dict[str, object]:
    api = "https://api.github.com/users/" + login.replace("[", "%5B").replace(
        "]", "%5D"
    )
    return {
        "login": login,
        "id": identifier,
        "node_id": node_id,
        "avatar_url": avatar_url,
        "gravatar_id": "",
        "url": api,
        "html_url": html_url,
        "followers_url": f"{api}/followers",
        "following_url": f"{api}/following{{/other_user}}",
        "gists_url": f"{api}/gists{{/gist_id}}",
        "starred_url": f"{api}/starred{{/owner}}{{/repo}}",
        "subscriptions_url": f"{api}/subscriptions",
        "organizations_url": f"{api}/orgs",
        "repos_url": f"{api}/repos",
        "events_url": f"{api}/events{{/privacy}}",
        "received_events_url": f"{api}/received_events",
        "type": kind,
        "user_view_type": "public",
        "site_admin": False,
    }


CODERABBIT_STATUS_CREATOR = _github_account(
    CODERABBIT_STATUS_CREATOR_LOGIN,
    CODERABBIT_STATUS_CREATOR_ID,
    "BOT_kgDOCCSy2w",
    f"https://avatars.githubusercontent.com/in/{CODERABBIT_APP_ID}?v=4",
    "https://github.com/apps/coderabbitai",
    "Bot",
)
FIXTURE_CI_CREATOR = _github_account(
    "fixture-ci[bot]",
    5_550_001,
    "BOT_kgDOfixtureci",
    "https://avatars.githubusercontent.com/in/555001?v=4",
    "https://github.com/apps/fixture-ci",
    "Bot",
)
IMPOSTOR_CREATOR = _github_account(
    "fixture-impostor",
    4_242_424,
    "U_kgDOfixtureimpostor",
    "https://avatars.githubusercontent.com/u/4242424?v=4",
    "https://github.com/fixture-impostor",
    "User",
)
COPILOT_REVIEWER = _github_account(
    "copilot-pull-request-reviewer[bot]",
    175_728_472,
    "BOT_kgDOCnlnWA",
    "https://avatars.githubusercontent.com/in/946600?v=4",
    "https://github.com/apps/copilot-pull-request-reviewer",
    "Bot",
)
GREPTILE_REVIEWER = _github_account(
    "greptile-apps[bot]",
    165_735_046,
    "BOT_kgDOCeDqhg",
    "https://avatars.githubusercontent.com/in/867647?v=4",
    "https://github.com/apps/greptile-apps",
    "Bot",
)
UNASSOCIATED_PERSON = _github_account(
    "fixture-outsider",
    4_343_434,
    "U_kgDOfixtureoutsider",
    "https://avatars.githubusercontent.com/u/4343434?v=4",
    "https://github.com/fixture-outsider",
    "User",
)
LATER_STATUS_ID = 54_265_861_234
LATER_STATUS_TIME = "2026-09-16T08:02:11Z"


def _commit_status(
    identifier: int,
    state: str,
    created_at: str,
    description: str | None,
    *,
    context: str = CODERABBIT_CONTEXT,
    creator: dict[str, object] | None = None,
    node_id: str | None = None,
) -> dict[str, object]:
    author = copy.deepcopy(CODERABBIT_STATUS_CREATOR if creator is None else creator)
    return {
        "url": STATUS_URL,
        "avatar_url": author["avatar_url"],
        "id": identifier,
        "node_id": f"SC_fixture{identifier}" if node_id is None else node_id,
        "state": state,
        "description": description,
        "target_url": None,
        "context": context,
        "created_at": created_at,
        "updated_at": created_at,
        "creator": author,
    }


def _coderabbit_status_history() -> list[dict[str, object]]:
    # The live PR #287 head's CodeRabbit history, newest first as GitHub lists it.
    return [
        _commit_status(
            54_265_797_954,
            "success",
            "2026-09-16T07:55:17Z",
            "Review completed",
            node_id="SC_kwDOLl3dHs8AAAAMon5dQg",
        ),
        _commit_status(
            54_265_732_210,
            "pending",
            "2026-09-16T07:53:57Z",
            "Review in progress",
            node_id="SC_kwDOLl3dHs8AAAAMon1ccg",
        ),
    ]


def _unrelated_status(
    identifier: int, state: str, created_at: str
) -> dict[str, object]:
    return _commit_status(
        identifier,
        state,
        created_at,
        f"Fixture audit {state}",
        context="fixture/external-audit",
        creator=FIXTURE_CI_CREATOR,
    )


def _later_coderabbit_status(
    state: str, description: str, *, creator: dict[str, object] | None = None
) -> dict[str, object]:
    return _commit_status(
        LATER_STATUS_ID, state, LATER_STATUS_TIME, description, creator=creator
    )


def _review(
    identifier: int,
    user: dict[str, object],
    state: str,
    commit_id: str,
    submitted_at: str,
    *,
    body: str = "",
    association: str = "NONE",
) -> dict[str, object]:
    pull_html = "https://github.com/nisavid/dotfiles/pull/286"
    html = f"{pull_html}#pullrequestreview-{identifier}"
    pull = "https://api.github.com/repos/nisavid/dotfiles/pulls/286"
    return {
        "id": identifier,
        "node_id": f"PRR_fixture{identifier}",
        "user": copy.deepcopy(user),
        "body": body,
        "state": state,
        "html_url": html,
        "pull_request_url": pull,
        "author_association": association,
        "_links": {"html": {"href": html}, "pull_request": {"href": pull}},
        "submitted_at": submitted_at,
        "commit_id": commit_id,
    }


def _coderabbit_review_history() -> list[dict[str, object]]:
    # The merged PR #322 review history, remapped onto the fixture commits: every
    # review reports association NONE, and CodeRabbit alone approves the head.
    return [
        _review(
            5_309_961_369,
            COPILOT_REVIEWER,
            "COMMENTED",
            REVIEWED_SOURCE_COMMIT,
            "2026-09-24T20:39:32Z",
            body=(
                "Copilot was unable to review this pull request because the user"
                " who requested the review has reached their quota limit."
            ),
        ),
        _review(
            5_310_021_366,
            CODERABBIT_STATUS_CREATOR,
            "DISMISSED",
            REVIEWED_SOURCE_COMMIT,
            "2026-09-24T20:45:42Z",
        ),
        _review(
            5_310_098_055,
            CODERABBIT_STATUS_CREATOR,
            "APPROVED",
            HEAD_COMMIT,
            "2026-09-24T20:53:03Z",
        ),
    ]


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
        status_contexts = {
            source["context"]
            for source in REQUIRED_CHECK_SOURCES
            if source["source"] == "commit-status"
        }
        check_runs = []
        for index, check in enumerate(REQUIRED_CHECKS, start=1):
            if check["context"] in status_contexts:
                continue
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
            "review_decision": "APPROVED",
            "review_threads": [
                {"id": "PRRT_resolved", "isResolved": True, "isOutdated": False}
            ],
            "requested_reviewers": {"users": [], "teams": []},
            "check_runs": {"total_count": len(check_runs), "check_runs": check_runs},
            "statuses": _coderabbit_status_history(),
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
                    if scenario in {{"graphql-pagination", "review-decision-changed-between-pages"}}:
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
                    decision = fixture["review_decision"]
                    if (
                        scenario == "review-decision-changed-between-pages"
                        and cursor is not None
                    ) or (
                        scenario == "review-decision-changed-between-observations"
                        and counters[path] > 1
                    ):
                        decision = "CHANGES_REQUESTED"
                    value = {{
                        "data": {{
                            "repository": {{
                                "pullRequest": {{
                                    "number": 286,
                                    "baseRefOid": {BASE_COMMIT!r},
                                    "headRefOid": {HEAD_COMMIT!r},
                                    "reviewDecision": decision,
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
                    if scenario == "review-decision-missing":
                        del value["data"]["repository"]["pullRequest"]["reviewDecision"]
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
                elif path == f"{{prefix}}/commits/{HEAD_COMMIT}/statuses":
                    statuses = fixture["statuses"]
                    if (
                        scenario == "statuses-changed-between-observations"
                        and counters[path] > 1
                    ):
                        rerun = json.loads(json.dumps(statuses[0]))
                        rerun["id"] += 1_000
                        rerun["node_id"] = "SC_fixture_rerun"
                        rerun["created_at"] = "2026-09-16T08:10:00Z"
                        rerun["updated_at"] = "2026-09-16T08:10:00Z"
                        statuses = [rerun, *statuses]
                    if scenario == "statuses-unbounded":
                        value = []
                        for index in range(100):
                            record = json.loads(json.dumps(statuses[0]))
                            record["id"] = 60_000_000_000 - page * 1_000 - index
                            record["node_id"] = f"SC_fixture_unbounded_{{page}}_{{index}}"
                            record["context"] = f"fixture/unbounded-{{page}}-{{index:02d}}"
                            value.append(record)
                    else:
                        start = (page - 1) * 100
                        value = statuses[start : start + 100]
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
                if scenario.startswith("incidental-drift-per-"):
                    generation = counters[path]
                    if scenario == "incidental-drift-per-collection":
                        generation = (generation + 1) // 2
                    stamp = "2026-09-26T00:%02d:00Z" % generation
                    if path.endswith("/pulls/286"):
                        for side in ("base", "head"):
                            repository = value[side]["repo"]
                            repository["default_branch"] = "main"
                            repository["pushed_at"] = stamp
                            repository["updated_at"] = stamp
                            repository["size"] = 1_000 + generation
                            for count in (
                                "open_issues",
                                "open_issues_count",
                                "stargazers_count",
                                "watchers",
                                "watchers_count",
                                "forks",
                                "forks_count",
                            ):
                                repository[count] = generation
                    if path.endswith("/check-runs"):
                        for run in value["check_runs"]:
                            run["app"]["slug"] = "github-actions"
                            run["app"]["updated_at"] = stamp
                if scenario.startswith("bound-drift-per-read-"):
                    generation = counters[path]
                    field = scenario[len("bound-drift-per-read-"):]
                    if field == "pull-updated" and path.endswith("/pulls/286"):
                        value["updated_at"] = "2026-09-26T00:%02d:00Z" % generation
                    if field == "pull-comments" and path.endswith("/pulls/286"):
                        value["comments"] = generation
                    if field == "repository-setting" and path.endswith("/pulls/286"):
                        value["base"]["repo"]["allow_auto_merge"] = generation % 2 == 0
                    if field == "app-permissions" and path.endswith("/check-runs"):
                        for run in value["check_runs"]:
                            run["app"]["permissions"] = dict(
                                checks="write" if generation % 2 else "read"
                            )
                if scenario == "malformed-incidental-count" and path.endswith("/pulls/286"):
                    value["head"]["repo"]["forks_count"] = -1
                if scenario == "malformed-incidental-timestamp" and path.endswith("/pulls/286"):
                    value["head"]["repo"]["pushed_at"] = "2026-09-26 00:00:00"
                if scenario == "malformed-incidental-base-count" and path.endswith("/pulls/286"):
                    value["base"]["repo"]["open_issues_count"] = True
                if scenario == "malformed-incidental-app-timestamp" and path.endswith("/check-runs"):
                    value["check_runs"][0]["app"]["updated_at"] = 123
                if scenario == "null-incidental-timestamp" and path.endswith("/pulls/286"):
                    value["base"]["repo"]["pushed_at"] = None
                if scenario == "protection-drift" and path.endswith("/branches/main/protection"):
                    value["enforce_admins"]["enabled"] = False
                if scenario == "retired-check-readded" and path.endswith("/branches/main/protection"):
                    retired = {RETIRED_REQUIRED_CHECK!r}
                    value["required_status_checks"]["contexts"].append(retired["context"])
                    value["required_status_checks"]["checks"].append(retired)
                if scenario == "required-check-app-drift" and path.endswith("/branches/main/protection"):
                    for check in value["required_status_checks"]["checks"]:
                        if check["context"] == {EXCEPTION_CONTEXT!r}:
                            check["app_id"] += 1
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
            "schema": REQUEST_SCHEMA,
            "repository": "nisavid/dotfiles",
            "branch": "main",
            "pull_request_number": 286,
            "base_commit": BASE_COMMIT,
            "head_commit": HEAD_COMMIT,
            "reviewed_source_commit": REVIEWED_SOURCE_COMMIT,
            "required_checks": REQUIRED_CHECKS,
            "required_check_sources": REQUIRED_CHECK_SOURCES,
            "trusted_reviewers": TRUSTED_REVIEWERS,
            "expected_protection": self._protection(),
            "expected_effective_rules": [],
            "expected_rulesets": [],
        }

    def _write_request(self, value: dict[str, object] | None = None) -> None:
        request = self._request_value() if value is None else value
        self.request.write_bytes(_json_bytes(request))
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
        self, *faults: str, state: Path | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        target = self.state if state is None else state
        fault_name = "-".join(faults)
        harness = self.private / f"collector-{fault_name}-{target.name}-fault.py"
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
                real_open = namespace["os"].open
                real_fsync = namespace["os"].fsync
                real_selector = namespace["selectors"].DefaultSelector
                capture_runner = namespace["CaptureRunner"]
                real_get = capture_runner.get
                created = []
                fired = False
                record_descriptors = set()
                record_synced = False
                directory_fsync_failed = False
                selector_signalled = False
                group_signalled = False
                probe_faulted = False
                signal_faulted = False
                faults = frozenset({faults!r})
                known_faults = {{
                    "between-capture-signal",
                    "mkdir-signal",
                    "popen-signal",
                    "popen-signal-unverified",
                    "record-directory-fsync-failure",
                    "record-file-fsync-failure",
                    "registered-signal",
                    "rename-signal-failure",
                    "rename-signal-success",
                    "transient-probe-eperm",
                    "transient-signal-eperm",
                }}
                if not faults or not faults <= known_faults:
                    raise AssertionError(sorted(faults))

                def faulting_popen(*args, **kwargs):
                    process = real_popen(*args, **kwargs)
                    created.append(process)
                    os.kill(os.getpid(), signal.SIGTERM)
                    return process

                def faulting_mkdir(path, mode=0o777, *, dir_fd=None):
                    global fired
                    result = real_mkdir(path, mode, dir_fd=dir_fd)
                    if not fired and dir_fd is not None and os.fspath(path) == {target.name!r}:
                        fired = True
                        os.kill(os.getpid(), signal.SIGTERM)
                    return result

                def uncertain_killpg(pgid, signum):
                    if signum == 0:
                        raise PermissionError(errno.EPERM, "synthetic uncertain group probe")
                    return real_killpg(pgid, signum)

                # Darwin answers EPERM while a group holds only exiting or unreaped
                # members; each fault injects one such answer and then defers to the
                # real group.
                def transient_eperm_killpg(pgid, signum):
                    global group_signalled, probe_faulted, signal_faulted
                    if signum == 0:
                        if (
                            "transient-probe-eperm" in faults
                            and group_signalled
                            and not probe_faulted
                        ):
                            probe_faulted = True
                            raise PermissionError(errno.EPERM, "synthetic transient group probe")
                        return real_killpg(pgid, signum)
                    if "transient-signal-eperm" in faults and not signal_faulted:
                        signal_faulted = True
                        raise PermissionError(errno.EPERM, "synthetic transient group signal")
                    group_signalled = True
                    return real_killpg(pgid, signum)

                def signaling_selector(*args, **kwargs):
                    global selector_signalled
                    if not selector_signalled:
                        selector_signalled = True
                        os.kill(os.getpid(), signal.SIGTERM)
                    return real_selector(*args, **kwargs)

                def signaling_get(self, label, endpoint):
                    value = real_get(self, label, endpoint)
                    if label == "a-pull":
                        os.kill(os.getpid(), signal.SIGTERM)
                    return value

                def signaling_rename(*args, **kwargs):
                    if os.fspath(args[1]) != "ready.json":
                        return real_rename(*args, **kwargs)
                    if "rename-signal-failure" in faults:
                        os.kill(os.getpid(), signal.SIGTERM)
                        raise OSError(errno.EIO, "synthetic ready rename failure")
                    result = real_rename(*args, **kwargs)
                    os.kill(os.getpid(), signal.SIGTERM)
                    return result

                def observing_open(path, flags, mode=0o777, *, dir_fd=None):
                    descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                    name = os.path.basename(os.fspath(path)).lstrip(".")
                    if name.startswith("interrupted.json"):
                        record_descriptors.add(descriptor)
                    return descriptor

                def faulting_fsync(descriptor):
                    global directory_fsync_failed, record_synced
                    if descriptor in record_descriptors:
                        if "record-file-fsync-failure" in faults:
                            raise OSError(errno.EIO, "synthetic record fsync failure")
                        result = real_fsync(descriptor)
                        record_synced = True
                        return result
                    if (
                        "record-directory-fsync-failure" in faults
                        and record_synced
                        and not directory_fsync_failed
                    ):
                        directory_fsync_failed = True
                        raise OSError(errno.EIO, "synthetic record directory fsync failure")
                    return real_fsync(descriptor)

                if faults & {{"popen-signal", "popen-signal-unverified"}}:
                    namespace["subprocess"].Popen = faulting_popen
                if "popen-signal-unverified" in faults:
                    namespace["os"].killpg = uncertain_killpg
                if faults & {{"transient-probe-eperm", "transient-signal-eperm"}}:
                    namespace["os"].killpg = transient_eperm_killpg
                if "registered-signal" in faults:
                    namespace["selectors"].DefaultSelector = signaling_selector
                if "mkdir-signal" in faults:
                    namespace["os"].mkdir = faulting_mkdir
                if "between-capture-signal" in faults:
                    capture_runner.get = signaling_get
                if faults & {{"rename-signal-success", "rename-signal-failure"}}:
                    namespace["os"].rename = signaling_rename
                if faults & {{"record-directory-fsync-failure", "record-file-fsync-failure"}}:
                    namespace["os"].open = observing_open
                    namespace["os"].fsync = faulting_fsync

                try:
                    status = namespace["main"]([
                        "--request", {os.fspath(self.request)!r},
                        "--state-directory", {os.fspath(target)!r},
                    ])
                finally:
                    namespace["subprocess"].Popen = real_popen
                    namespace["os"].mkdir = real_mkdir
                    namespace["os"].killpg = real_killpg
                    namespace["os"].rename = real_rename
                    namespace["os"].open = real_open
                    namespace["os"].fsync = real_fsync
                    namespace["selectors"].DefaultSelector = real_selector
                    capture_runner.get = real_get
                    for process in created:
                        if process.poll() is None:
                            try:
                                real_killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            process.wait(timeout=2)
                if ("transient-probe-eperm" in faults and not probe_faulted) or (
                    "transient-signal-eperm" in faults and not signal_faulted
                ):
                    raise SystemExit(86)
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

    def _call_count(self) -> int:
        return len(self._calls()) if self.calls.exists() else 0

    def _endpoints_since(self, offset: int) -> list[str]:
        if not self.calls.exists():
            return []
        return [arguments[-1] for arguments in self._calls()[offset:]]

    def _assert_interruption_recorded(self, state: Path, signum: int) -> None:
        record = state / "interrupted.json"
        self.assertEqual(
            record.read_bytes(),
            _json_bytes(
                {
                    "caught_signal": int(signum),
                    "outcome": "interrupted",
                    "schema": INTERRUPTED_SCHEMA,
                }
            ),
        )
        info = record.lstat()
        self.assertTrue(stat.S_ISREG(info.st_mode))
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
        self.assertEqual(info.st_uid, os.getuid())
        self.assertEqual(info.st_nlink, 1)
        self.assertFalse((state / "ready.json").exists())
        self.assertEqual([name for name in os.listdir(state) if name[0] == "."], [])

    def _assert_no_interruption_record(self, state: Path) -> None:
        self.assertFalse((state / "interrupted.json").exists())
        self.assertEqual([name for name in os.listdir(state) if name[0] == "."], [])

    def _write_status_fixture(
        self,
        statuses: list[dict[str, object]],
        extra_check_runs: tuple[dict[str, object], ...] = (),
    ) -> None:
        fixture = self._fixture_value()
        fixture["statuses"] = statuses
        runs = fixture["check_runs"]["check_runs"]
        runs.extend(copy.deepcopy(list(extra_check_runs)))
        fixture["check_runs"]["total_count"] = len(runs)
        self.fixture.write_bytes(_json_bytes(fixture))

    def _observe_statuses(
        self, statuses: list[dict[str, object]], state: Path
    ) -> dict[str, object]:
        self._write_status_fixture(statuses)

        result = self._run(state)

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"recovery preimage ready\n")
        self._assert_read_only_calls()
        return json.loads(self._observations_path(state).read_bytes())

    def _assert_status_evidence_rejected(
        self,
        statuses: list[dict[str, object]],
        state: Path,
        *,
        extra_check_runs: tuple[dict[str, object], ...] = (),
    ) -> None:
        self._write_status_fixture(statuses, extra_check_runs)
        self._assert_first_observation_rejected(state)

    def _write_review_fixture(
        self, reviews: list[dict[str, object]], *, author_id: int | None = None
    ) -> None:
        fixture = self._fixture_value()
        fixture["reviews"] = reviews
        if author_id is not None:
            fixture["pull"]["user"]["id"] = author_id
        self.fixture.write_bytes(_json_bytes(fixture))

    def _write_trusted_reviewers(self, reviewers: object) -> None:
        request = self._request_value()
        request["trusted_reviewers"] = reviewers
        self._write_request(request)

    def _assert_first_observation_rejected(self, state: Path) -> None:
        offset = self._call_count()

        result = self._run(state)

        self.assertEqual(result.returncode, 1, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation failed\n")
        self.assertFalse((state / "ready.json").exists())
        self.assertFalse((state / "interrupted.json").exists())
        # The first observation read every endpoint, statuses included, and was
        # rejected before a second observation began.
        endpoints = self._endpoints_since(offset)
        self.assertEqual(endpoints.count(PULL_ENDPOINT), 1)
        self.assertEqual(endpoints.count(STATUSES_FIRST_PAGE), 1)
        self.assertEqual(endpoints.count(RULESETS_FIRST_PAGE), 1)
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
            'arguments=("$@")\n'
            "method=GET\n"
            "while (( $# > 0 )); do\n"
            '  if [[ $1 == --method ]]; then\n'
            "    method=$2\n"
            "    shift 2\n"
            "  else\n"
            "    shift\n"
            "  fi\n"
            "done\n"
            'mutation_phase=$FAKE_GH_STATE_DIR/dispatch-mutation.active\n'
            'if [[ $method == PATCH || $method == PUT ]]; then\n'
            '  : >"$mutation_phase"\n'
            "fi\n"
            'if [[ -e $mutation_phase ]]; then\n'
            f"  exec {shlex.quote(os.fspath(self.zsh))} "
            f'{shlex.quote(os.fspath(RECOVERY_GH_FIXTURE))} "${{arguments[@]}}"\n'
            "fi\n"
            f'exec {shlex.quote(os.fspath(collector_gh))} "${{arguments[@]}}"\n',
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
        self,
        scenario: str,
        *,
        rejected_gate: str | None = None,
        require_admin_api_contract: bool = False,
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
        elif rejected_gate in RELEVANT_STATE_DRIFTS:
            original, drifted = self._relevant_state_drift(rejected_gate)
            self.fixture.write_bytes(_json_bytes(original))
            drifted_fixture = self.private / "drifted-fixture.json"
            self._write_private_json(drifted_fixture, drifted)
            # Allowed incidental metadata also moves between the collections.
            self._set_scenario("incidental-drift-per-collection")
            interstitial = (
                f"cp {shlex.quote(os.fspath(drifted_fixture))} "
                f"{shlex.quote(os.fspath(self.fixture))}\n"
            )
        elif rejected_gate == "tampered-original-capture":
            interstitial = (
                "print -rn -- ' ' >>"
                '"$RECOVERY_STATE_DIRECTORY/captures/001-a-pull.stdout.json"\n'
            )
        elif rejected_gate == "tampered-original-ready-during-replay":
            interstitial = textwrap.dedent("""\
                cmp() {
                  if [[ ${argv[-1]} == "$RECOVERY_FRESH_STATE_DIRECTORY.stdout" ]]; then
                    print -rn -- ' ' >>"$RECOVERY_STATE_DIRECTORY/ready.json"
                  fi
                  command cmp "$@"
                }
                """)
        elif rejected_gate == "tampered-fresh-capture":
            # The gate compares the fresh stdout just after the fresh collection.
            interstitial = textwrap.dedent("""\
                cmp() {
                  local capture=$RECOVERY_FRESH_STATE_DIRECTORY/captures/001-a-pull.stdout.json
                  if [[ ${argv[-1]} == "$RECOVERY_FRESH_STATE_DIRECTORY.stdout" ]]; then
                    print -rn -- ' ' >>"$capture"
                  fi
                  command cmp "$@"
                }
                """)
        elif rejected_gate == "unapproved-ready-digest":
            interstitial = f"RECOVERY_PREIMAGE_READY_SHA256={'0' * 64}\n"
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
        if require_admin_api_contract:
            environment.update(
                {
                    "FAKE_GH_REQUIRE_ADMIN_API_CONTRACT": "1",
                    "GH_HOST": "enterprise.invalid",
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
            "--method PUT" in line
            and "repos/nisavid/dotfiles/pulls/286/merge" in line
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
        *,
        require_admin_api_contract: bool = False,
    ) -> None:
        result, mutation = self._run_recovery_procedure(
            scenario, require_admin_api_contract=require_admin_api_contract
        )

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
        if rejected_gate in RELEVANT_STATE_DRIFTS:
            self.assertEqual(result.stderr, b"")
        self.assertEqual((mutation / "calls.log").read_bytes(), b"")
        self.assertEqual(
            (mutation / "protection.json").read_bytes(),
            (mutation / "preimage.json").read_bytes(),
        )
        self.assertEqual(self._recovery_merge_attempts(mutation), 0)
        self.assertEqual(self._recovery_restore_attempts(mutation), 0)

    def _relevant_state_drift(
        self, name: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        original = self._fixture_value()
        original["pull"].update(
            title="Recover the age admission signer",
            comments=0,
            updated_at="2026-09-24T21:00:00Z",
        )
        original["pull"]["base"]["repo"]["allow_auto_merge"] = False
        drifted = copy.deepcopy(original)
        if name == "pull-discussion-drift":
            drifted["pull"].update(comments=1, updated_at="2026-09-24T21:05:00Z")
        elif name == "pull-title-drift":
            drifted["pull"]["title"] = "Recover a different signer"
        elif name == "repository-setting-drift":
            drifted["pull"]["base"]["repo"]["allow_auto_merge"] = True
        elif name == "check-run-identity-drift":
            for run in drifted["check_runs"]["check_runs"]:
                if run["name"] == EXCEPTION_CONTEXT:
                    run["id"] = 104
        elif name == "status-drift":
            drifted["statuses"].insert(
                0, _later_coderabbit_status("success", "Review completed")
            )
        elif name == "approval-drift":
            drifted["reviews"].append(
                _review(
                    5_310_300_000,
                    CODERABBIT_STATUS_CREATOR,
                    "APPROVED",
                    HEAD_COMMIT,
                    "2026-09-24T21:10:00Z",
                )
            )
        elif name == "thread-drift":
            drifted["review_threads"].append(
                {"id": "PRRT_resolved_later", "isResolved": True, "isOutdated": False}
            )
        else:
            raise AssertionError(f"unknown relevant-state drift: {name}")
        return original, drifted

    def _assert_relevant_drift_rejected(self, name: str) -> None:
        self._assert_ready_gate_rejected(name)
        # The fresh collection itself was ready; only its relevant-state comparison
        # with the owner-approved collection stopped the entry gate.
        fresh = self.private / "procedure-private/fresh"
        self.assertTrue((fresh / "ready.json").is_file())

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

    def test_recovery_administration_pins_the_github_api_contract(
        self,
    ) -> None:
        self._assert_recovery_outcome(
            "success",
            "zero",
            "preimage",
            1,
            1,
            require_admin_api_contract=True,
        )

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

    def test_incidental_metadata_drift_between_collections_is_replayed(
        self,
    ) -> None:
        self._set_scenario("incidental-drift-per-collection")

        self._assert_recovery_outcome("success", "zero", "preimage", 1, 1)

        procedure_private = self.private / "procedure-private"
        original = json.loads((procedure_private / "initial/ready.json").read_bytes())
        fresh = json.loads((procedure_private / "fresh/ready.json").read_bytes())
        self.assertNotEqual(original["artifacts"], fresh["artifacts"])
        self.assertEqual(original["payloads"], fresh["payloads"])

    def test_target_pull_discussion_drift_is_rejected_before_mutation(self) -> None:
        self._assert_relevant_drift_rejected("pull-discussion-drift")

    def test_target_pull_title_drift_is_rejected_before_mutation(self) -> None:
        self._assert_relevant_drift_rejected("pull-title-drift")

    def test_repository_setting_drift_is_rejected_before_mutation(self) -> None:
        self._assert_relevant_drift_rejected("repository-setting-drift")

    def test_check_run_identity_drift_is_rejected_before_mutation(self) -> None:
        self._assert_relevant_drift_rejected("check-run-identity-drift")

    def test_status_drift_is_rejected_before_mutation(self) -> None:
        self._assert_relevant_drift_rejected("status-drift")

    def test_approval_drift_is_rejected_before_mutation(self) -> None:
        self._assert_relevant_drift_rejected("approval-drift")

    def test_review_thread_drift_is_rejected_before_mutation(self) -> None:
        self._assert_relevant_drift_rejected("thread-drift")

    def test_tampered_original_capture_is_rejected_before_replay(self) -> None:
        self._assert_ready_gate_rejected("tampered-original-capture")
        self.assertFalse((self.private / "procedure-private/fresh").exists())

    def test_tampered_fresh_capture_is_rejected_before_mutation(self) -> None:
        self._assert_ready_gate_rejected("tampered-fresh-capture")
        self.assertTrue(
            (self.private / "procedure-private/fresh/ready.json").is_file()
        )

    def test_original_ready_changed_during_replay_is_rejected_before_mutation(
        self,
    ) -> None:
        self._assert_ready_gate_rejected("tampered-original-ready-during-replay")
        self.assertTrue(
            (self.private / "procedure-private/fresh/ready.json").is_file()
        )

    def test_unapproved_ready_digest_is_rejected_before_replay(self) -> None:
        self._assert_ready_gate_rejected("unapproved-ready-digest")
        self.assertFalse((self.private / "procedure-private/fresh").exists())

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
        self.assertEqual([run["id"] for run in matches], [4, 101, 102])
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

    def test_coderabbit_status_history_satisfies_its_required_context(self) -> None:
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        ready = json.loads((self.state / "ready.json").read_bytes())
        self.assertEqual(
            ready["binding"]["required_check_sources"],
            sorted(REQUIRED_CHECK_SOURCES, key=lambda source: str(source["context"])),
        )
        observations = json.loads(self._observations_path(self.state).read_bytes())
        self.assertEqual(observations["statuses"], _coderabbit_status_history())
        self.assertEqual(
            [status["state"] for status in observations["statuses"]],
            ["success", "pending"],
        )
        self.assertNotIn(
            CODERABBIT_CONTEXT,
            {run["name"] for run in observations["check_runs"]["check_runs"]},
        )
        restore = json.loads(
            (self.state / ready["payloads"]["restore_checks"]["path"]).read_bytes()
        )
        self.assertEqual(
            restore,
            {
                "strict": True,
                "checks": sorted(
                    REQUIRED_CHECKS,
                    key=lambda check: (str(check["context"]), int(check["app_id"])),
                ),
            },
        )
        self.assertIn(
            {"context": CODERABBIT_CONTEXT, "app_id": CODERABBIT_APP_ID},
            restore["checks"],
        )
        self._assert_read_only_calls()

    def test_superseded_unrelated_status_failure_is_accepted_when_latest_succeeds(
        self,
    ) -> None:
        statuses = [
            _unrelated_status(54_265_830_000, "success", "2026-09-16T07:58:00Z"),
            *_coderabbit_status_history(),
            _unrelated_status(54_265_500_000, "failure", "2026-09-16T07:40:00Z"),
        ]

        observations = self._observe_statuses(statuses, self.state)

        self.assertEqual(observations["statuses"], statuses)

    def test_commit_statuses_are_fully_paginated_across_pages(self) -> None:
        newer = [
            _commit_status(
                54_266_000_000 - index,
                "success",
                f"2026-09-16T08:{59 - index // 60:02d}:{59 - index % 60:02d}Z",
                "Fixture audit success",
                context=f"fixture/newer-{index:02d}",
                creator=FIXTURE_CI_CREATOR,
            )
            for index in range(99)
        ]
        older = [
            _commit_status(
                54_265_000_000 - index,
                "success",
                f"2026-09-16T06:{59 - index // 60:02d}:{59 - index % 60:02d}Z",
                "Fixture audit success",
                context=f"fixture/older-{index:02d}",
                creator=FIXTURE_CI_CREATOR,
            )
            for index in range(49)
        ]
        # CodeRabbit's success ends page one; its superseded pending starts page two.
        statuses = [*newer, *_coderabbit_status_history(), *older]

        observations = self._observe_statuses(statuses, self.state)

        self.assertEqual(observations["statuses"], statuses)
        endpoints = self._endpoints_since(0)
        for page, expected in ((1, 2), (2, 2), (3, 0)):
            self.assertEqual(
                endpoints.count(f"{STATUSES_ENDPOINT}?per_page=100&page={page}"),
                expected,
            )

    def test_latest_pending_required_status_leaves_no_ready_file(self) -> None:
        self._assert_status_evidence_rejected(
            [
                _later_coderabbit_status("pending", "Review in progress"),
                *_coderabbit_status_history(),
            ],
            self.state,
        )

    def test_latest_failed_required_status_leaves_no_ready_file(self) -> None:
        self._assert_status_evidence_rejected(
            [
                _later_coderabbit_status("failure", "Review failed"),
                *_coderabbit_status_history(),
            ],
            self.state,
        )

    def test_latest_errored_required_status_leaves_no_ready_file(self) -> None:
        self._assert_status_evidence_rejected(
            [
                _later_coderabbit_status("error", "Review errored"),
                *_coderabbit_status_history(),
            ],
            self.state,
        )

    def test_missing_required_status_leaves_no_ready_file(self) -> None:
        cases = {
            "no-statuses": [],
            "unrelated-only": [
                _unrelated_status(54_265_830_000, "success", "2026-09-16T07:58:00Z")
            ],
        }
        for name, statuses in cases.items():
            with self.subTest(name):
                self._assert_status_evidence_rejected(statuses, self.private / name)

    def test_foreign_creator_required_status_leaves_no_ready_file(self) -> None:
        history = _coderabbit_status_history()
        other_id = copy.deepcopy(CODERABBIT_STATUS_CREATOR)
        other_id["id"] = CODERABBIT_STATUS_CREATOR_ID + 1
        other_login = copy.deepcopy(CODERABBIT_STATUS_CREATOR)
        other_login["login"] = "coderabbit[bot]"
        anonymous = copy.deepcopy(history)
        anonymous[0]["creator"] = None
        cases = {
            "foreign-latest": [
                _later_coderabbit_status(
                    "success", "Review completed", creator=IMPOSTOR_CREATOR
                ),
                *history,
            ],
            "pinned-login-other-id": [
                _later_coderabbit_status(
                    "success", "Review completed", creator=other_id
                ),
                *history,
            ],
            "pinned-id-other-login": [
                _later_coderabbit_status(
                    "success", "Review completed", creator=other_login
                ),
                *history,
            ],
            "foreign-superseded": [
                *history,
                _commit_status(
                    54_265_700_001,
                    "pending",
                    "2026-09-16T07:50:00Z",
                    "Review in progress",
                    creator=IMPOSTOR_CREATOR,
                ),
            ],
            "creator-absent": anonymous,
        }
        for name, statuses in cases.items():
            with self.subTest(name):
                self._assert_status_evidence_rejected(statuses, self.private / name)

    def test_protection_app_id_is_not_accepted_as_the_status_creator(self) -> None:
        request = self._request_value()
        sources = copy.deepcopy(REQUIRED_CHECK_SOURCES)
        for source in sources:
            if source["context"] == CODERABBIT_CONTEXT:
                source["creator_id"] = CODERABBIT_APP_ID
        request["required_check_sources"] = sources
        self._write_request(request)

        self._assert_status_evidence_rejected(_coderabbit_status_history(), self.state)

    def test_status_change_between_observations_leaves_no_ready_file(self) -> None:
        self._set_scenario("statuses-changed-between-observations")

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation failed\n")
        self.assertFalse((self.state / "ready.json").exists())
        endpoints = self._endpoints_since(0)
        self.assertEqual(endpoints.count(PULL_ENDPOINT), 2)
        self.assertEqual(endpoints.count(STATUSES_FIRST_PAGE), 2)
        captures = self.state / "captures"
        first = json.loads(
            next(captures.glob("*-a-statuses-p1.stdout.json")).read_bytes()
        )
        second = json.loads(
            next(captures.glob("*-b-statuses-p1.stdout.json")).read_bytes()
        )
        self.assertEqual(first, _coderabbit_status_history())
        self.assertEqual(second[1:], first)
        self.assertEqual(second[0]["state"], "success")
        self._assert_read_only_calls()

    def test_duplicate_status_ids_leave_no_ready_file(self) -> None:
        history = _coderabbit_status_history()
        reused = copy.deepcopy(history[1])
        reused["id"] = history[0]["id"]
        cases = {
            "repeated-record": [history[0], copy.deepcopy(history[0]), history[1]],
            "reused-id": [history[0], reused],
        }
        for name, statuses in cases.items():
            with self.subTest(name):
                self._assert_status_evidence_rejected(statuses, self.private / name)

    def test_incomplete_status_pagination_leaves_no_ready_file(self) -> None:
        self._set_scenario("statuses-unbounded")

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation failed\n")
        self.assertFalse((self.state / "ready.json").exists())
        endpoints = self._endpoints_since(0)
        self.assertEqual(
            [
                endpoint
                for endpoint in endpoints
                if endpoint.startswith(STATUSES_ENDPOINT)
            ],
            [f"{STATUSES_ENDPOINT}?per_page=100&page={page}" for page in range(1, 6)],
        )
        self.assertEqual(endpoints.count(PULL_ENDPOINT), 1)
        self._assert_read_only_calls()

    def test_unrelated_latest_non_success_status_leaves_no_ready_file(self) -> None:
        superseded = _unrelated_status(
            54_265_500_000, "success", "2026-09-16T07:40:00Z"
        )
        for state in ("pending", "failure", "error"):
            with self.subTest(state):
                latest = _unrelated_status(
                    54_265_830_000, state, "2026-09-16T07:58:00Z"
                )
                self._assert_status_evidence_rejected(
                    [latest, *_coderabbit_status_history(), superseded],
                    self.private / f"unrelated-{state}",
                )

    def test_ambiguous_latest_status_leaves_no_ready_file(self) -> None:
        history = _coderabbit_status_history()
        tied = copy.deepcopy(history)
        tied[0]["created_at"] = tied[0]["updated_at"] = history[1]["created_at"]
        newer_listed_second = copy.deepcopy(history)
        newer_listed_second[1]["created_at"] = "2026-09-16T07:56:30Z"
        newer_listed_second[1]["updated_at"] = "2026-09-16T07:56:30Z"
        id_inverted = copy.deepcopy(history)
        id_inverted[0]["id"] = int(history[1]["id"]) - 1
        updated = copy.deepcopy(history)
        updated[0]["updated_at"] = "2026-09-16T07:56:00Z"
        cases = {
            "tied-creation-times": tied,
            "oldest-listed-first": [history[1], history[0]],
            "newer-pending-listed-second": newer_listed_second,
            "id-order-contradicts-time": id_inverted,
            "updated-after-creation": updated,
        }
        for name, statuses in cases.items():
            with self.subTest(name):
                self._assert_status_evidence_rejected(statuses, self.private / name)

    def test_status_for_another_commit_leaves_no_ready_file(self) -> None:
        statuses = _coderabbit_status_history()
        statuses[0]["url"] = STATUS_URL.replace(HEAD_COMMIT, "d" * 40)

        self._assert_status_evidence_rejected(statuses, self.state)

    def test_required_context_from_the_other_source_leaves_no_ready_file(
        self,
    ) -> None:
        coderabbit_run = {
            "id": 5,
            "name": CODERABBIT_CONTEXT,
            "head_sha": HEAD_COMMIT,
            "status": "completed",
            "conclusion": "success",
            "app": {"id": CODERABBIT_APP_ID},
        }
        with self.subTest("check-run-for-status-context"):
            self._assert_status_evidence_rejected(
                _coderabbit_status_history(),
                self.private / "check-run-for-status-context",
                extra_check_runs=(coderabbit_run,),
            )
        with self.subTest("status-for-check-run-context"):
            self._assert_status_evidence_rejected(
                [
                    _commit_status(
                        LATER_STATUS_ID,
                        "success",
                        LATER_STATUS_TIME,
                        "Fixture audit success",
                        context="zsh deployment portability",
                        creator=FIXTURE_CI_CREATOR,
                    ),
                    *_coderabbit_status_history(),
                ],
                self.private / "status-for-check-run-context",
            )

    def test_malformed_status_leaves_no_ready_file(self) -> None:
        mutations: dict[str, tuple[str, object]] = {
            "unknown-state": ("state", "neutral"),
            "structured-state": ("state", ["success"]),
            "fractional-timestamp": ("created_at", "2026-09-16T07:55:17.000Z"),
            "empty-context": ("context", ""),
            "nonpositive-id": ("id", 0),
            "boolean-id": ("id", True),
        }
        for name, (field, replacement) in mutations.items():
            with self.subTest(name):
                statuses = _coderabbit_status_history()
                statuses[0][field] = replacement
                if field == "created_at":
                    statuses[0]["updated_at"] = replacement
                self._assert_status_evidence_rejected(statuses, self.private / name)

    def test_request_without_status_sources_fails_before_state_creation(self) -> None:
        request = self._request_value()
        request["schema"] = "issue286-recovery-preimage-request/v1"
        del request["required_check_sources"]
        self._write_request(request)

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation failed\n")
        self.assertFalse(self.state.exists())
        self.assertFalse(self.calls.exists())

    def test_required_check_source_violations_fail_before_state_creation(
        self,
    ) -> None:
        def sources_with(
            context: str, *records: dict[str, object]
        ) -> list[dict[str, object]]:
            kept = [
                copy.deepcopy(source)
                for source in REQUIRED_CHECK_SOURCES
                if source["context"] != context
            ]
            return [*kept, *records]

        def status_source(**changes: object) -> dict[str, object]:
            record: dict[str, object] = {
                "context": CODERABBIT_CONTEXT,
                "source": "commit-status",
                "creator_id": CODERABBIT_STATUS_CREATOR_ID,
                "creator_login": CODERABBIT_STATUS_CREATOR_LOGIN,
            }
            record.update(changes)
            return record

        without_login = status_source()
        del without_login["creator_login"]
        cases: dict[str, object] = {
            "exception-as-commit-status": sources_with(
                EXCEPTION_CONTEXT, status_source(context=EXCEPTION_CONTEXT)
            ),
            "check-run-app-differs-from-protection": sources_with(
                "zsh deployment portability",
                {
                    "context": "zsh deployment portability",
                    "source": "check-run",
                    "app_id": 15369,
                },
            ),
            "creator-id-as-check-run-app": sources_with(
                CODERABBIT_CONTEXT,
                {
                    "context": CODERABBIT_CONTEXT,
                    "source": "check-run",
                    "app_id": CODERABBIT_STATUS_CREATOR_ID,
                },
            ),
            "creator-login-missing": sources_with(CODERABBIT_CONTEXT, without_login),
            "creator-login-invalid": sources_with(
                CODERABBIT_CONTEXT, status_source(creator_login="coderabbitai/bot")
            ),
            "creator-id-nonpositive": sources_with(
                CODERABBIT_CONTEXT, status_source(creator_id=0)
            ),
            "creator-id-boolean": sources_with(
                CODERABBIT_CONTEXT, status_source(creator_id=True)
            ),
            "status-source-with-app-id": sources_with(
                CODERABBIT_CONTEXT, status_source(app_id=CODERABBIT_APP_ID)
            ),
            "unknown-source-kind": sources_with(
                CODERABBIT_CONTEXT, status_source(source="combined-status")
            ),
            "unprotected-context": sources_with(
                CODERABBIT_CONTEXT, status_source(context="Greptile Review")
            ),
            "duplicate-context": sources_with(
                "zsh deployment portability", status_source()
            ),
            "missing-source": sources_with("zsh deployment portability"),
            "extra-source": [*REQUIRED_CHECK_SOURCES, status_source()],
            "not-a-list": {CODERABBIT_CONTEXT: status_source()},
        }
        for name, sources in cases.items():
            with self.subTest(name):
                request = self._request_value()
                request["required_check_sources"] = sources
                self._write_request(request)

                result = self._run()

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr, b"recovery preimage preparation failed\n"
                )
                self.assertFalse(self.state.exists())
                self.assertFalse(self.calls.exists())

    def test_pinned_reviewer_approval_without_association_satisfies_review(
        self,
    ) -> None:
        reviews = _coderabbit_review_history()
        self._write_review_fixture(reviews)

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"recovery preimage ready\n")
        ready = json.loads((self.state / "ready.json").read_bytes())
        self.assertEqual(ready["binding"]["trusted_reviewers"], TRUSTED_REVIEWERS)
        observations = json.loads(self._observations_path(self.state).read_bytes())
        self.assertEqual(observations["reviews"], reviews)
        self.assertEqual(
            {review["author_association"] for review in observations["reviews"]},
            {"NONE"},
        )
        self._assert_read_only_calls()

    def test_current_approval_accepts_a_superseded_change_request(self) -> None:
        # PR #327 retains CodeRabbit's earlier change request after the same
        # reviewer approved the current commit and GitHub reports APPROVED.
        reviews = _coderabbit_review_history()
        reviews[1]["state"] = "CHANGES_REQUESTED"
        self._write_review_fixture(reviews)

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"recovery preimage ready\n")
        self.assertTrue((self.state / "ready.json").is_file())
        observations = json.loads(self._observations_path(self.state).read_bytes())
        self.assertEqual(observations["reviews"], reviews)
        self._assert_read_only_calls()

    def test_unapproved_current_decision_leaves_no_ready_file(self) -> None:
        for name, decision in {
            "changes-requested": "CHANGES_REQUESTED",
            "review-required": "REVIEW_REQUIRED",
            "null": None,
            "unknown": "COMMENTED",
            "wrong-type": True,
        }.items():
            with self.subTest(name):
                fixture = self._fixture_value()
                fixture["review_decision"] = decision
                self.fixture.write_bytes(_json_bytes(fixture))
                state = self.private / name

                result = self._run(state)

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"recovery preimage preparation failed\n")
                self.assertFalse((state / "ready.json").exists())
                self._assert_read_only_calls()

    def test_missing_current_review_decision_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("review-decision-missing")

    def test_review_decision_change_between_pages_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("review-decision-changed-between-pages")
        inputs = [json.loads(line) for line in self.graphql_inputs.read_text().splitlines()]
        self.assertEqual(
            [item["variables"]["threadsCursor"] for item in inputs],
            [None, "fixture-page-one"],
        )

    def test_review_decision_change_between_observations_leaves_no_ready_file(
        self,
    ) -> None:
        self._assert_failed_without_ready("review-decision-changed-between-observations")
        self.assertEqual(len(self.graphql_inputs.read_text().splitlines()), 2)

    def test_current_change_request_after_approval_leaves_no_ready_file(self) -> None:
        fixture = self._fixture_value()
        fixture["reviews"] = [
            *_coderabbit_review_history(),
            _review(
                5_310_200_000,
                CODERABBIT_STATUS_CREATOR,
                "CHANGES_REQUESTED",
                HEAD_COMMIT,
                "2026-09-24T21:00:00Z",
            ),
        ]
        fixture["review_decision"] = "CHANGES_REQUESTED"
        self.fixture.write_bytes(_json_bytes(fixture))
        self._assert_failed_without_ready("success")

    def test_retracted_approval_blocks_even_when_github_reports_approved(self) -> None:
        reviews = _coderabbit_review_history()
        retraction = _review(
            5_310_200_000,
            CODERABBIT_STATUS_CREATOR,
            "CHANGES_REQUESTED",
            HEAD_COMMIT,
            "2026-09-24T21:00:00Z",
        )
        self._write_review_fixture([*reviews, retraction])
        self._assert_first_observation_rejected(self.state)

    def test_same_commit_approval_supersedes_change_request_and_survives_comment(
        self,
    ) -> None:
        reviews = _coderabbit_review_history()
        reviews[1].update(state="CHANGES_REQUESTED", commit_id=HEAD_COMMIT)
        reviews.append(_review(
            5_310_200_000, CODERABBIT_STATUS_CREATOR, "COMMENTED", HEAD_COMMIT,
            "2026-09-24T21:00:00Z",
        ))
        self._write_review_fixture(list(reversed(reviews)))

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertTrue((self.state / "ready.json").is_file())
        self._assert_read_only_calls()

    def test_reviewers_cannot_supersede_each_others_change_requests(self) -> None:
        reviews = _coderabbit_review_history()
        reviews[1]["state"] = "CHANGES_REQUESTED"
        reviews[-1]["user"] = {"id": 2, "login": "fixture-reviewer"}
        reviews[-1]["author_association"] = "COLLABORATOR"
        self._write_review_fixture(reviews)
        self._assert_first_observation_rejected(self.state)

    def test_dismissed_current_opinion_needs_another_qualifying_approval(self) -> None:
        reviews = _coderabbit_review_history()
        dismissal = _review(
            5_310_200_000, CODERABBIT_STATUS_CREATOR, "DISMISSED", HEAD_COMMIT,
            "2026-09-24T21:00:00Z",
        )
        self._write_review_fixture([*reviews, dismissal])
        self._assert_first_observation_rejected(self.private / "no-other-approval")
        other = self._fixture_value()["reviews"][0]
        self._write_review_fixture([*reviews, dismissal, other])

        result = self._run(self.state)

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertTrue((self.state / "ready.json").is_file())
        self._assert_read_only_calls()

    def test_ambiguous_or_invalid_review_order_leaves_no_ready_file(self) -> None:
        for name, timestamp in {
            "tied": "2026-09-24T20:53:03Z",
            "tied-reversed": "2026-09-24T20:53:03Z",
            "missing": None,
            "invalid": "not-a-time",
        }.items():
            with self.subTest(name):
                reviews = _coderabbit_review_history()
                reviews[1].update(state="CHANGES_REQUESTED", submitted_at=timestamp)
                if name == "tied-reversed":
                    reviews.reverse()
                self._write_review_fixture(reviews)
                self._assert_first_observation_rejected(self.private / name)

    def test_unique_latest_approval_accepts_tied_historical_opinions(self) -> None:
        reviews = _coderabbit_review_history()
        reviews[1]["state"] = "CHANGES_REQUESTED"
        older = copy.deepcopy(reviews[1])
        older.update(id=5_310_021_367, state="DISMISSED")
        for name, ordered in {
            "ascending": [reviews[0], reviews[1], older, reviews[2]],
            "descending": [reviews[2], older, reviews[1], reviews[0]],
        }.items():
            with self.subTest(name):
                self._write_review_fixture(ordered)
                state = self.private / name
                result = self._run(state)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
                self.assertTrue((state / "ready.json").is_file())
        self._assert_read_only_calls()

    def test_pending_review_blocks_an_approved_pull_request(self) -> None:
        reviews = _coderabbit_review_history()
        pending = copy.deepcopy(reviews[-1])
        pending.update(id=5_310_200_000, state="PENDING", submitted_at=None)
        self._write_review_fixture([*reviews, pending])
        self._assert_first_observation_rejected(self.state)

    def test_unpinned_exact_head_approval_leaves_no_ready_file(self) -> None:
        def with_head_approval(
            user: dict[str, object], **changes: object
        ) -> list[dict[str, object]]:
            account = copy.deepcopy(user)
            account.update(changes)
            approval = _review(
                5_310_200_000, account, "APPROVED", HEAD_COMMIT, "2026-09-24T21:00:00Z"
            )
            return [*_coderabbit_review_history(), approval]

        cases = {
            # Merged PR #304 also carried an association-NONE Greptile approval.
            "unpinned-bot": with_head_approval(GREPTILE_REVIEWER),
            "pinned-login-other-id": with_head_approval(
                CODERABBIT_STATUS_CREATOR, id=CODERABBIT_STATUS_CREATOR_ID + 1
            ),
            "pinned-id-other-login": with_head_approval(
                CODERABBIT_STATUS_CREATOR, login="coderabbit[bot]"
            ),
            "unassociated-person": with_head_approval(UNASSOCIATED_PERSON),
        }
        for name, reviews in cases.items():
            with self.subTest(name):
                self._write_review_fixture(reviews)
                self._assert_first_observation_rejected(self.private / name)
        with self.subTest("no-reviewer-pinned"):
            state = self.private / "no-reviewer-pinned"
            self._write_trusted_reviewers([])
            self._write_review_fixture(_coderabbit_review_history())
            self._assert_first_observation_rejected(state)

    def test_pinned_reviewer_keeps_final_commit_and_independence_rules(
        self,
    ) -> None:
        history = _coderabbit_review_history()
        earlier = copy.deepcopy(history)
        earlier[-1]["commit_id"] = REVIEWED_SOURCE_COMMIT
        cases = {
            "approval-of-an-earlier-commit": (earlier, None),
            "pinned-reviewer-is-the-author": (history, CODERABBIT_STATUS_CREATOR_ID),
        }
        for name, (reviews, author_id) in cases.items():
            with self.subTest(name):
                self._write_review_fixture(reviews, author_id=author_id)
                self._assert_first_observation_rejected(self.private / name)

    def test_trusted_reviewer_violations_fail_before_state_creation(self) -> None:
        coderabbit = TRUSTED_REVIEWERS[0]
        other_id = CODERABBIT_STATUS_CREATOR_ID + 1
        requests: dict[str, dict[str, object]] = {}
        for name, reviewers in {
            "not-a-list": coderabbit,
            "extra-field": [{**coderabbit, "type": "Bot"}],
            "missing-login": [{"id": coderabbit["id"]}],
            "nonpositive-id": [{**coderabbit, "id": 0}],
            "boolean-id": [{**coderabbit, "id": True}],
            "person-login": [{**coderabbit, "login": "coderabbitai"}],
            "invalid-login": [{**coderabbit, "login": "coderabbitai/bot[bot]"}],
            "duplicate-id": [coderabbit, {**coderabbit, "login": "coderabbit[bot]"}],
            "duplicate-login": [coderabbit, {**coderabbit, "id": other_id}],
        }.items():
            request = self._request_value()
            request["trusted_reviewers"] = reviewers
            requests[name] = request
        requests["missing"] = self._request_value()
        del requests["missing"]["trusted_reviewers"]
        for name, request in requests.items():
            with self.subTest(name):
                self._write_request(request)

                result = self._run()

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr, b"recovery preimage preparation failed\n"
                )
                self.assertFalse(self.state.exists())
                self.assertFalse(self.calls.exists())

    def test_unrelated_protection_drift_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("protection-drift")

    def test_readded_retired_required_check_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("retired-check-readded")

    def test_required_check_app_drift_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("required-check-app-drift")

    def test_stale_evidence_between_observations_leaves_no_ready_file(self) -> None:
        self._assert_failed_without_ready("stale-between-passes")

    def test_incidental_metadata_drift_between_observations_is_ready(self) -> None:
        fixture = self._fixture_value()
        fixture["pull"].update(comments=3, updated_at="2026-09-24T21:00:00Z")
        self.fixture.write_bytes(_json_bytes(fixture))
        self._set_scenario("incidental-drift-per-read")

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"recovery preimage ready\n")
        ready = json.loads((self.state / "ready.json").read_bytes())
        recorded = {
            artifact["path"]: artifact["sha256"] for artifact in ready["artifacts"]
        }
        raw: dict[str, list[dict[str, object]]] = {}
        for label in ("pull", "check-runs-p1"):
            captures = [
                next((self.state / "captures").glob(f"*-{name}-{label}.stdout.json"))
                for name in ("a", "b")
            ]
            for capture in captures:
                self.assertEqual(
                    recorded[f"captures/{capture.name}"],
                    _sha256(capture.read_bytes()),
                )
            raw[label] = [json.loads(capture.read_bytes()) for capture in captures]
        self.assertNotEqual(
            raw["pull"][0]["base"]["repo"]["pushed_at"],
            raw["pull"][1]["base"]["repo"]["pushed_at"],
        )
        self.assertNotEqual(
            raw["check-runs-p1"][0]["check_runs"][0]["app"]["updated_at"],
            raw["check-runs-p1"][1]["check_runs"][0]["app"]["updated_at"],
        )
        observations = json.loads(self._observations_path(self.state).read_bytes())
        self.assertEqual(observations["pull"]["comments"], 3)
        self.assertEqual(observations["pull"]["updated_at"], "2026-09-24T21:00:00Z")
        for side in ("base", "head"):
            self.assertEqual(
                observations["pull"][side]["repo"],
                {"default_branch": "main", "full_name": "nisavid/dotfiles"},
            )
        self.assertEqual(
            [run["app"] for run in observations["check_runs"]["check_runs"]],
            [{"id": 15368, "slug": "github-actions"}] * 3,
        )
        self._assert_read_only_calls()

    def test_bound_drift_between_observations_leaves_no_ready_file(self) -> None:
        for field in (
            "pull-updated",
            "pull-comments",
            "repository-setting",
            "app-permissions",
        ):
            with self.subTest(field):
                self._set_scenario(f"bound-drift-per-read-{field}")
                state = self.private / field
                offset = self._call_count()

                result = self._run(state)

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr, b"recovery preimage preparation failed\n"
                )
                self.assertFalse((state / "ready.json").exists())
                # Both complete observations were read; their comparison failed.
                endpoints = self._endpoints_since(offset)
                self.assertEqual(endpoints.count(PULL_ENDPOINT), 2)
                self.assertEqual(endpoints.count(RULESETS_FIRST_PAGE), 2)
        self._assert_read_only_calls()

    def test_malformed_incidental_metadata_leaves_no_ready_file(self) -> None:
        for scenario in (
            "malformed-incidental-count",
            "malformed-incidental-timestamp",
            "malformed-incidental-base-count",
            "malformed-incidental-app-timestamp",
        ):
            with self.subTest(scenario):
                self._set_scenario(scenario)
                state = self.private / scenario
                offset = self._call_count()

                result = self._run(state)

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr, b"recovery preimage preparation failed\n"
                )
                self.assertFalse((state / "ready.json").exists())
                endpoints = self._endpoints_since(offset)
                self.assertEqual(endpoints.count(PULL_ENDPOINT), 1)
                self.assertEqual(endpoints.count(RULESETS_FIRST_PAGE), 1)
        self._assert_read_only_calls()

    def test_null_incidental_timestamp_is_ready(self) -> None:
        self._set_scenario("null-incidental-timestamp")

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertTrue((self.state / "ready.json").is_file())
        observations = json.loads(self._observations_path(self.state).read_bytes())
        self.assertNotIn("pushed_at", observations["pull"]["base"]["repo"])
        capture = next((self.state / "captures").glob("*-a-pull.stdout.json"))
        self.assertIsNone(json.loads(capture.read_bytes())["base"]["repo"]["pushed_at"])
        self._assert_read_only_calls()

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
        self._assert_interruption_recorded(self.state, signal.SIGTERM)
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
        self._assert_interruption_recorded(self.state, signal.SIGTERM)

    def test_signal_during_state_mkdir_retains_state_without_publishing(self) -> None:
        result = self._run_with_collector_fault("mkdir-signal")

        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation interrupted\n")
        self.assertTrue(self.state.is_dir())
        self.assertFalse((self.state / "ready.json").exists())
        self.assertFalse(self.calls.exists())
        # The signal preceded every capture, so the state-level record is the only
        # evidence of the interruption.
        self.assertEqual(os.listdir(self.state), ["interrupted.json"])
        self._assert_interruption_recorded(self.state, signal.SIGTERM)

    def test_signal_between_captures_is_durably_recorded(self) -> None:
        result = self._run_with_collector_fault("between-capture-signal")

        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation interrupted\n")
        self.assertEqual(
            sorted(os.listdir(self.state)),
            ["captures", "interrupted.json", "payloads"],
        )
        self._assert_interruption_recorded(self.state, signal.SIGTERM)
        statuses = sorted((self.state / "captures").glob("*.status.json"))
        self.assertEqual([path.name for path in statuses], ["001-a-pull.status.json"])
        self.assertEqual(
            json.loads(statuses[0].read_bytes()),
            {"exit_status": 0, "method": "GET", "outcome": "exited"},
        )
        self.assertEqual(os.listdir(self.state / "payloads"), [])
        self.assertEqual(self._endpoints_since(0), [PULL_ENDPOINT])

    def test_signal_after_ready_rename_defers_to_the_successful_commit(self) -> None:
        result = self._run_with_collector_fault("rename-signal-success")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"recovery preimage ready\n")
        self.assertEqual(result.stderr, b"")
        self.assertTrue((self.state / "ready.json").is_file())
        self._assert_no_interruption_record(self.state)

    def test_failed_ready_rename_restores_signal_delivery_and_publishes_nothing(
        self,
    ) -> None:
        result = self._run_with_collector_fault("rename-signal-failure")

        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"recovery preimage preparation interrupted\n")
        self.assertFalse((self.state / "ready.json").exists())
        self._assert_interruption_recorded(self.state, signal.SIGTERM)

    def test_unsynced_interruption_record_fails_closed(self) -> None:
        triggers = {
            "before-capture": "mkdir-signal",
            "between-captures": "between-capture-signal",
            "ready-commit-failure": "rename-signal-failure",
        }
        durability_faults = {
            "file": "record-file-fsync-failure",
            "directory": "record-directory-fsync-failure",
        }
        for trigger_name, trigger in triggers.items():
            for fault_name, fault in durability_faults.items():
                with self.subTest(trigger=trigger_name, fault=fault_name):
                    state = self.private / f"state-{trigger_name}-{fault_name}"

                    result = self._run_with_collector_fault(
                        trigger, fault, state=state
                    )

                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, b"")
                    self.assertEqual(
                        result.stderr, b"recovery preimage preparation failed\n"
                    )
                    self.assertTrue(state.is_dir())
                    self.assertFalse((state / "ready.json").exists())
                    self._assert_no_interruption_record(state)

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
        self._assert_no_interruption_record(self.state)

    def test_transient_group_eperm_does_not_abort_verified_retirement(self) -> None:
        # macos-14 answers EPERM for a group whose only members are exiting or
        # unreaped: after the caught signal's group SIGTERM, and after retirement's
        # own signals. One such answer must defer to the absence proof that follows.
        self._set_scenario("hang")
        cases = {
            "probe-after-caught-signal": ("registered-signal", "transient-probe-eperm"),
            "probe-after-retirement-signal": ("popen-signal", "transient-probe-eperm"),
            "retirement-signal": ("popen-signal", "transient-signal-eperm"),
        }
        for name, faults in cases.items():
            with self.subTest(name):
                state = self.private / f"state-{name}"

                result = self._run_with_collector_fault(*faults, state=state)

                self.assertEqual(
                    result.returncode,
                    128 + signal.SIGTERM,
                    result.stderr.decode("utf-8", "replace"),
                )
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr, b"recovery preimage preparation interrupted\n"
                )
                statuses = sorted((state / "captures").glob("*.status.json"))
                self.assertEqual(len(statuses), 1)
                self.assertEqual(
                    json.loads(statuses[0].read_bytes()),
                    {
                        "caught_signal": signal.SIGTERM,
                        "method": "GET",
                        "outcome": "interrupted",
                    },
                )
                self._assert_interruption_recorded(state, signal.SIGTERM)

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
            self._assert_interruption_recorded(self.state, signal.SIGTERM)
            self._assert_process_and_group_absent(
                int(record["pid"]), int(record["pgid"])
            )
        finally:
            self._force_process_group_cleanup(int(record["pgid"]))

    def test_request_outside_the_four_check_contract_fails_before_state_creation(
        self,
    ) -> None:
        without_age_check = [
            check for check in REQUIRED_CHECKS if check["context"] != EXCEPTION_CONTEXT
        ]
        cases = {
            "retired check restored": [*REQUIRED_CHECKS, RETIRED_REQUIRED_CHECK],
            "exception-window set": without_age_check,
            "age check omitted": [*without_age_check, RETIRED_REQUIRED_CHECK],
        }
        for name, checks in cases.items():
            with self.subTest(name):
                request = self._request_value()
                request["required_checks"] = checks
                status = request["expected_protection"]["required_status_checks"]
                status["contexts"] = [check["context"] for check in checks]
                status["checks"] = checks
                self.request.write_bytes(_json_bytes(request))
                self.request.chmod(0o600)

                result = self._run()

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr, b"recovery preimage preparation failed\n"
                )
                self.assertFalse(self.state.exists())
                self.assertFalse(self.calls.exists())

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
        self.assertEqual(ready["schema"], READY_SCHEMA)
        self.assertEqual(ready["outcome"], "ready")
        self.assertEqual(ready["graphql_query_sha256"], GRAPHQL_QUERY_SHA256)
        self.assertEqual(ready["request_sha256"], _sha256(self.request.read_bytes()))
        self.assertEqual(
            set(ready["binding"]),
            {
                "base_commit",
                "branch",
                "head_commit",
                "pull_request_number",
                "repository",
                "required_check_sources",
                "required_checks",
                "reviewed_source_commit",
                "trusted_reviewers",
            },
        )
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
        self.assertEqual(len(restore["checks"]), 4)
        self.assertEqual(len(exception["checks"]), 3)
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
        self.assertEqual(endpoints.count(STATUSES_FIRST_PAGE), 2)
        self.assertEqual(endpoints.count(RULESETS_FIRST_PAGE), 2)
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
