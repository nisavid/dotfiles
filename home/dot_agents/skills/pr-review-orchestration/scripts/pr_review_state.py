#!/usr/bin/env python3
"""Fetch and summarize thread-aware GitHub PR review state."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LEDGER_ROOT = Path.home() / ".local" / "state" / "agent-pr-review"


def build_pr_query(
    repo: str,
    pr_number: int,
    cursors: dict[str, str | None],
    include: dict[str, bool] | None = None,
) -> tuple[str, dict[str, Any]]:
    owner, name = split_repo(repo)
    include = include or {"threads": True, "reviews": True, "checks": True, "review_requests": True}
    query = """
query PrReviewState(
  $owner: String!
  $name: String!
  $prNumber: Int!
  $threadsCursor: String
  $reviewsCursor: String
  $checksCursor: String
  $reviewRequestsCursor: String
  $includeThreads: Boolean!
  $includeReviews: Boolean!
  $includeChecks: Boolean!
  $includeReviewRequests: Boolean!
) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $prNumber) {
      number
      url
      isDraft
      baseRefName
      headRefName
      baseRefOid
      headRefOid
      reviewDecision
      mergeStateStatus
      mergeable
      reviewThreads(first: 100, after: $threadsCursor) @include(if: $includeThreads) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 100) {
            nodes {
              author { login }
              body
              createdAt
              url
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
      reviews(first: 100, after: $reviewsCursor) @include(if: $includeReviews) {
        nodes {
          author { login }
          state
          submittedAt
        }
        pageInfo { hasNextPage endCursor }
      }
      reviewRequests(first: 100, after: $reviewRequestsCursor) @include(if: $includeReviewRequests) {
        nodes {
          requestedReviewer {
            __typename
            ... on User { login }
            ... on Team { slug }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
      statusCheckRollup @include(if: $includeChecks) {
        contexts(first: 100, after: $checksCursor) {
          nodes {
            __typename
            ... on CheckRun {
              name
              status
              conclusion
            }
            ... on StatusContext {
              context
              state
            }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
  }
}
""".strip()
    variables = {
        "owner": owner,
        "name": name,
        "prNumber": pr_number,
        "threadsCursor": cursors.get("threads"),
        "reviewsCursor": cursors.get("reviews"),
        "checksCursor": cursors.get("checks"),
        "reviewRequestsCursor": cursors.get("review_requests"),
        "includeThreads": bool(include.get("threads")),
        "includeReviews": bool(include.get("reviews")),
        "includeChecks": bool(include.get("checks")),
        "includeReviewRequests": bool(include.get("review_requests")),
    }
    return query, variables


def split_repo(repo: str) -> tuple[str, str]:
    parts = repo.split("/", 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError("repo must be OWNER/REPO")
    return parts[0], parts[1]


def fetch_pages(repo: str, pr_number: int) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    cursors: dict[str, str | None] = {
        "threads": None,
        "reviews": None,
        "checks": None,
        "review_requests": None,
    }
    include = {key: True for key in cursors}
    while True:
        query, variables = build_pr_query(repo, pr_number, cursors, include=include)
        page = run_gh_graphql(query, variables)
        pages.append(page)
        page_info = page_infos(page)
        next_cursors = {
            "threads": cursor_if_next(page_info["threads"]),
            "reviews": cursor_if_next(page_info["reviews"]),
            "checks": cursor_if_next(page_info["checks"]),
            "review_requests": cursor_if_next(page_info["review_requests"]),
        }
        if not any(next_cursors.values()):
            hydrate_thread_comments(pages)
            return pages
        include = {key: value is not None for key, value in next_cursors.items()}
        cursors = next_cursors


def hydrate_thread_comments(pages: list[dict[str, Any]]) -> None:
    for page in pages:
        for thread in ((extract_pr(page).get("reviewThreads") or {}).get("nodes") or []):
            comments = thread.get("comments") or {}
            page_info = comments.get("pageInfo") or {}
            while page_info.get("hasNextPage"):
                next_page = fetch_thread_comments(thread["id"], page_info.get("endCursor"))
                next_comments = ((next_page.get("data") or {}).get("node") or {}).get("comments") or {}
                comments.setdefault("nodes", []).extend(next_comments.get("nodes") or [])
                page_info = next_comments.get("pageInfo") or {}
                comments["pageInfo"] = page_info


def fetch_thread_comments(thread_id: str, cursor: str | None) -> dict[str, Any]:
    query = """
query ThreadComments($threadId: ID!, $commentsCursor: String) {
  node(id: $threadId) {
    ... on PullRequestReviewThread {
      comments(first: 100, after: $commentsCursor) {
        nodes {
          author { login }
          body
          createdAt
          url
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""".strip()
    return run_gh_graphql(query, {"threadId": thread_id, "commentsCursor": cursor})


def run_gh_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    command = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is not None:
            command.extend(["-F", f"{key}={gh_field_value(value)}"])
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    return json.loads(completed.stdout)


def gh_field_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def state_from_pages(repo: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    owner, name = split_repo(repo)
    if not pages:
        raise ValueError("at least one page is required")

    pull_requests = [extract_pr(page) for page in pages]
    pr = pull_requests[0]
    review_threads = collect_review_threads(pull_requests)
    reviews = collect_nodes(pull_requests, "reviews")
    review_requests = collect_nodes(pull_requests, "reviewRequests")
    checks = collect_checks(pull_requests)
    unresolved_threads = [summarize_thread(thread, pr["headRefOid"]) for thread in review_threads if not thread.get("isResolved")]
    requested_reviewers, requested_teams = summarize_review_requests(review_requests)
    normalized_checks = [normalize_check(check) for check in checks]
    pagination_complete = is_pagination_complete(pull_requests)
    next_blocker = classify_blocker(pr, unresolved_threads, requested_reviewers, requested_teams, normalized_checks, pagination_complete)

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "repo": {
            "owner": owner,
            "name": name,
            "base_ref": pr.get("baseRefName"),
            "head_ref": pr.get("headRefName"),
        },
        "pr": {
            "number": pr.get("number"),
            "url": pr.get("url"),
            "draft": bool(pr.get("isDraft")),
        },
        "diff": {
            "head_sha": pr.get("headRefOid"),
            "base_sha": pr.get("baseRefOid"),
            "diff_id": pr.get("headRefOid"),
        },
        "cycles": {
            "local_review_count": 0,
            "external_completed_count": 0,
            "external_failed_count": 0,
        },
        "local_readiness": {
            "acceptance_matrix": [],
            "changed_file_risk_map": [],
            "unhappy_paths": [],
            "verification": [],
            "untested_risks": [],
        },
        "local_reviews": [],
        "external_review_attempts": [],
        "github_state": {
            "merge_state": pr.get("mergeStateStatus"),
            "mergeable": pr.get("mergeable"),
            "review_decision": pr.get("reviewDecision"),
            "requested_reviewers": requested_reviewers,
            "requested_teams": requested_teams,
            "checks": normalized_checks,
            "unresolved_threads": unresolved_threads,
            "reviews": summarize_reviews(reviews),
            "pagination_complete": pagination_complete,
        },
        "review_items": [],
        "decisions": [],
        "next_blocker": next_blocker,
        "merge_ready": next_blocker is None,
        "updated_at": now,
    }


def extract_pr(page: dict[str, Any]) -> dict[str, Any]:
    try:
        pr = page["data"]["repository"]["pullRequest"]
    except KeyError as error:
        raise ValueError(f"missing pullRequest in page: {error}") from error
    if pr is None:
        raise ValueError("pullRequest was null")
    return pr


def collect_nodes(pull_requests: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for pr in pull_requests:
        nodes.extend((pr.get(key) or {}).get("nodes") or [])
    return nodes


def collect_review_threads(pull_requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    threads_by_id: dict[str, dict[str, Any]] = {}
    anonymous_threads: list[dict[str, Any]] = []
    for pr in pull_requests:
        for thread in (pr.get("reviewThreads") or {}).get("nodes") or []:
            thread_id = thread.get("id")
            if not thread_id:
                anonymous_threads.append(thread)
                continue
            if thread_id not in threads_by_id:
                threads_by_id[thread_id] = json.loads(json.dumps(thread))
                continue
            existing = threads_by_id[thread_id]
            existing["isResolved"] = thread.get("isResolved", existing.get("isResolved"))
            existing["isOutdated"] = thread.get("isOutdated", existing.get("isOutdated"))
            existing["path"] = thread.get("path") or existing.get("path")
            existing["line"] = thread.get("line") if thread.get("line") is not None else existing.get("line")
            existing_comments = (existing.setdefault("comments", {}).setdefault("nodes", []))
            seen_urls = {comment.get("url") for comment in existing_comments}
            for comment in ((thread.get("comments") or {}).get("nodes") or []):
                comment_url = comment.get("url")
                if comment_url not in seen_urls:
                    existing_comments.append(comment)
                    seen_urls.add(comment_url)
            existing["comments"]["pageInfo"] = (thread.get("comments") or {}).get("pageInfo") or existing["comments"].get("pageInfo") or {}
    return list(threads_by_id.values()) + anonymous_threads


def collect_checks(pull_requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for pr in pull_requests:
        rollup = pr.get("statusCheckRollup") or {}
        contexts = rollup.get("contexts") or {}
        nodes.extend(contexts.get("nodes") or [])
    return nodes


def summarize_thread(thread: dict[str, Any], diff_id: str | None) -> dict[str, Any]:
    comments = ((thread.get("comments") or {}).get("nodes") or [])
    latest = comments[-1] if comments else {}
    first = comments[0] if comments else {}
    latest_author = (latest.get("author") or {}).get("login")
    first_body = (first.get("body") or "").strip().splitlines()
    return {
        "id": thread.get("id"),
        "url": latest.get("url"),
        "path": thread.get("path"),
        "line": thread.get("line"),
        "author": ((first.get("author") or {}).get("login")),
        "latest_comment_author": latest_author,
        "latest_comment_created_at": latest.get("createdAt"),
        "summary": first_body[0] if first_body else "",
        "is_outdated": bool(thread.get("isOutdated")),
        "is_resolved": bool(thread.get("isResolved")),
        "associated_diff_id": diff_id,
    }


def summarize_review_requests(nodes: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    reviewers: list[str] = []
    teams: list[str] = []
    for node in nodes:
        requested = node.get("requestedReviewer") or {}
        if requested.get("__typename") == "Team":
            if requested.get("slug"):
                teams.append(requested["slug"])
        elif requested.get("login"):
            reviewers.append(requested["login"])
    return reviewers, teams


def normalize_check(node: dict[str, Any]) -> dict[str, Any]:
    if node.get("__typename") == "StatusContext":
        state = node.get("state")
        conclusion = "SUCCESS" if state == "SUCCESS" else state
        return {
            "name": node.get("context"),
            "status": state,
            "conclusion": conclusion,
        }
    return {
        "name": node.get("name"),
        "status": node.get("status"),
        "conclusion": node.get("conclusion"),
    }


def summarize_reviews(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "author": (node.get("author") or {}).get("login"),
            "state": node.get("state"),
            "submitted_at": node.get("submittedAt"),
        }
        for node in nodes
    ]


def classify_blocker(
    pr: dict[str, Any],
    unresolved_threads: list[dict[str, Any]],
    requested_reviewers: list[str],
    requested_teams: list[str],
    checks: list[dict[str, Any]],
    pagination_complete: bool,
) -> str | None:
    if not pagination_complete:
        return "pagination_incomplete"
    if pr.get("isDraft"):
        return "draft_pr"
    if requested_reviewers or requested_teams:
        return "requested_reviewers"
    active_threads = [thread for thread in unresolved_threads if not thread["is_outdated"]]
    outdated_threads = [thread for thread in unresolved_threads if thread["is_outdated"]]
    if active_threads:
        return "unresolved_review_threads"
    if outdated_threads:
        return "outdated_unresolved_review_threads"
    if any(not check_successful(check) for check in checks):
        return "checks_not_successful"
    review_decision = pr.get("reviewDecision")
    if review_decision not in (None, "", "APPROVED"):
        return "review_not_approved"
    merge_state = pr.get("mergeStateStatus")
    mergeable = pr.get("mergeable")
    if merge_state not in ("CLEAN", "HAS_HOOKS"):
        return "merge_state_not_clean"
    if mergeable not in (None, "MERGEABLE"):
        return "merge_state_not_clean"
    return None


def check_successful(check: dict[str, Any]) -> bool:
    status = check.get("status")
    conclusion = check.get("conclusion")
    return status in (None, "COMPLETED", "SUCCESS") and conclusion in (None, "SUCCESS", "NEUTRAL", "SKIPPED")


def page_infos(page: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pr = extract_pr(page)
    rollup = pr.get("statusCheckRollup") or {}
    contexts = rollup.get("contexts") or {}
    return {
        "threads": ((pr.get("reviewThreads") or {}).get("pageInfo") or {}),
        "reviews": ((pr.get("reviews") or {}).get("pageInfo") or {}),
        "checks": (contexts.get("pageInfo") or {}),
        "review_requests": ((pr.get("reviewRequests") or {}).get("pageInfo") or {}),
    }


def cursor_if_next(info: dict[str, Any]) -> str | None:
    if info.get("hasNextPage"):
        return info.get("endCursor")
    return None


def is_pagination_complete(pull_requests: list[dict[str, Any]]) -> bool:
    if not pull_requests:
        return False
    last_infos = page_infos({"data": {"repository": {"pullRequest": pull_requests[-1]}}})
    top_level_complete = not any((info or {}).get("hasNextPage") for info in last_infos.values())
    comments_complete = True
    for thread in collect_review_threads(pull_requests):
        comments_info = ((thread.get("comments") or {}).get("pageInfo") or {})
        if comments_info.get("hasNextPage"):
            comments_complete = False
            break
    return top_level_complete and comments_complete


def write_ledger(state: dict[str, Any], root: Path = DEFAULT_LEDGER_ROOT) -> Path:
    owner = state["repo"]["owner"]
    name = state["repo"]["name"]
    pr_number = str(state["pr"]["number"])
    directory = root / owner / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{pr_number}.json"
    merged = merge_existing_ledger(path, state)
    path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def merge_existing_ledger(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return state
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return state
    merged = dict(state)
    for key in (
        "cycles",
        "local_readiness",
        "local_reviews",
        "external_review_attempts",
        "review_items",
        "decisions",
    ):
        if key in existing:
            merged[key] = existing[key]
    return merged


def summary_text(state: dict[str, Any]) -> str:
    lines = [
        f"PR: {state['pr']['url']}",
        f"merge_ready: {str(state['merge_ready']).lower()}",
        f"next_blocker: {state['next_blocker'] or 'none'}",
        f"review_decision: {state['github_state']['review_decision'] or 'none'}",
        f"merge_state: {state['github_state']['merge_state'] or 'unknown'}",
        f"requested_reviewers: {', '.join(state['github_state']['requested_reviewers']) or 'none'}",
        f"requested_teams: {', '.join(state['github_state']['requested_teams']) or 'none'}",
        f"unresolved_threads: {len(state['github_state']['unresolved_threads'])}",
        f"checks: {len(state['github_state']['checks'])}",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Base repository as OWNER/REPO")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number in the base repository")
    parser.add_argument("--json", action="store_true", help="Print JSON state")
    parser.add_argument("--summary", action="store_true", help="Print terse human summary")
    parser.add_argument("--write-ledger", action="store_true", help="Persist JSON ledger under ~/.local/state/agent-pr-review")
    parser.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT, help="Ledger root directory")
    parser.add_argument("--fixture", action="append", type=Path, help="Read one or more fixture pages instead of calling gh")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.fixture:
        pages = [json.loads(path.read_text(encoding="utf-8")) for path in args.fixture]
    else:
        pages = fetch_pages(args.repo, args.pr)
    state = state_from_pages(args.repo, pages)
    if args.write_ledger:
        write_ledger(state, root=args.ledger_root)
    if args.json or not args.summary:
        print(json.dumps(state, indent=2, sort_keys=True))
    if args.summary:
        print(summary_text(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
