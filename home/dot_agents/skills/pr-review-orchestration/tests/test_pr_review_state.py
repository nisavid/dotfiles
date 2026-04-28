import json
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import pr_review_state


FIXTURE_DIR = SKILL_DIR / "scripts" / "fixtures"


def fixture(name):
    with (FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class PrReviewStateTests(unittest.TestCase):
    def test_builds_query_variables_for_base_repository(self):
        query, variables = pr_review_state.build_pr_query(
            repo="base-owner/base-repo",
            pr_number=7,
            cursors={"threads": None, "reviews": None, "checks": None, "review_requests": None},
            include={"threads": True, "reviews": True, "checks": True, "review_requests": True},
        )

        self.assertIn("pullRequest(number: $prNumber)", query)
        self.assertEqual(
            variables,
            {
                "owner": "base-owner",
                "name": "base-repo",
                "prNumber": 7,
                "threadsCursor": None,
                "reviewsCursor": None,
                "checksCursor": None,
                "reviewRequestsCursor": None,
                "includeThreads": True,
                "includeReviews": True,
                "includeChecks": True,
                "includeReviewRequests": True,
            },
        )

    def test_paginated_threads_are_merged_and_block_readiness(self):
        state = pr_review_state.state_from_pages(
            repo="base-owner/base-repo",
            pages=[fixture("paginated_page_1.json"), fixture("paginated_page_2.json")],
        )

        self.assertEqual(state["repo"]["owner"], "base-owner")
        self.assertEqual(state["pr"]["number"], 7)
        self.assertEqual(len(state["github_state"]["unresolved_threads"]), 2)
        self.assertEqual(state["github_state"]["pagination_complete"], True)
        self.assertEqual(state["next_blocker"], "unresolved_review_threads")
        self.assertFalse(state["merge_ready"])

    def test_paginated_comments_merge_by_thread_id(self):
        state = pr_review_state.state_from_pages(
            repo="base-owner/base-repo",
            pages=[fixture("paginated_comments_page_1.json"), fixture("paginated_comments_page_2.json")],
        )

        threads = state["github_state"]["unresolved_threads"]
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["id"], "comment-thread")
        self.assertEqual(threads[0]["latest_comment_author"], "second-reviewer")
        self.assertEqual(threads[0]["latest_comment_created_at"], "2026-04-28T00:02:00Z")
        self.assertEqual(state["github_state"]["pagination_complete"], True)

    def test_fetch_pages_hydrates_comments_with_thread_specific_query(self):
        calls = []

        def fake_graphql(query, variables):
            calls.append((query, variables))
            if "ThreadComments" in query:
                return {
                    "data": {
                        "node": {
                            "comments": {
                                "nodes": [
                                    {
                                        "author": {"login": "second-reviewer"},
                                        "body": "Second comment",
                                        "createdAt": "2026-04-28T00:02:00Z",
                                        "url": "https://github.com/base-owner/base-repo/pull/7#discussion_c2",
                                    }
                                ],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            return fixture("paginated_comments_page_1.json")

        original = pr_review_state.run_gh_graphql
        pr_review_state.run_gh_graphql = fake_graphql
        try:
            pages = pr_review_state.fetch_pages("base-owner/base-repo", 7)
        finally:
            pr_review_state.run_gh_graphql = original

        first_query, first_variables = calls[0]
        self.assertNotIn("commentsCursor", first_query)
        self.assertNotIn("commentsCursor", first_variables)
        self.assertEqual(calls[1][1]["threadId"], "comment-thread")
        comments = pages[0]["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]["comments"]
        self.assertEqual(len(comments["nodes"]), 2)
        self.assertEqual(comments["pageInfo"]["hasNextPage"], False)

    def test_paginated_review_requests_and_checks_are_merged(self):
        state = pr_review_state.state_from_pages(
            repo="base-owner/base-repo",
            pages=[fixture("paginated_requests_checks_page_1.json"), fixture("paginated_requests_checks_page_2.json")],
        )

        self.assertEqual(state["github_state"]["requested_reviewers"], ["Copilot"])
        self.assertEqual(state["github_state"]["requested_teams"], ["review-team"])
        self.assertEqual([check["name"] for check in state["github_state"]["checks"]], ["lint", "test"])
        self.assertEqual(state["next_blocker"], "requested_reviewers")

    def test_fetch_pages_only_requeries_active_top_level_connections(self):
        calls = []

        def fake_graphql(query, variables):
            calls.append((query, variables))
            if len(calls) == 1:
                return fixture("mixed_top_level_page_1.json")
            return fixture("mixed_top_level_page_2.json")

        original = pr_review_state.run_gh_graphql
        pr_review_state.run_gh_graphql = fake_graphql
        try:
            pages = pr_review_state.fetch_pages("base-owner/base-repo", 7)
        finally:
            pr_review_state.run_gh_graphql = original

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][1]["includeThreads"], False)
        self.assertEqual(calls[1][1]["includeReviews"], False)
        self.assertEqual(calls[1][1]["includeChecks"], False)
        self.assertEqual(calls[1][1]["includeReviewRequests"], True)
        state = pr_review_state.state_from_pages("base-owner/base-repo", pages)
        self.assertEqual(state["github_state"]["requested_reviewers"], ["Copilot", "ReviewerTwo"])
        self.assertEqual([check["name"] for check in state["github_state"]["checks"]], ["lint"])

    def test_gh_field_values_serialize_booleans_lowercase(self):
        self.assertEqual(pr_review_state.gh_field_value(True), "true")
        self.assertEqual(pr_review_state.gh_field_value(False), "false")
        self.assertEqual(pr_review_state.gh_field_value(7), "7")
        self.assertEqual(pr_review_state.gh_field_value("cursor"), "cursor")

    def test_outdated_threads_are_reported_separately(self):
        state = pr_review_state.state_from_pages(
            repo="base-owner/base-repo",
            pages=[fixture("outdated_thread.json")],
        )

        self.assertEqual(len(state["github_state"]["unresolved_threads"]), 1)
        self.assertEqual(state["github_state"]["unresolved_threads"][0]["is_outdated"], True)
        self.assertEqual(state["next_blocker"], "outdated_unresolved_review_threads")
        self.assertFalse(state["merge_ready"])

    def test_requested_reviewers_block_readiness(self):
        state = pr_review_state.state_from_pages(
            repo="base-owner/base-repo",
            pages=[fixture("requested_reviewer.json")],
        )

        self.assertEqual(state["github_state"]["requested_reviewers"], ["Copilot"])
        self.assertEqual(state["next_blocker"], "requested_reviewers")
        self.assertFalse(state["merge_ready"])

    def test_failed_checks_block_readiness(self):
        state = pr_review_state.state_from_pages(
            repo="base-owner/base-repo",
            pages=[fixture("failed_check.json")],
        )

        self.assertEqual(state["github_state"]["checks"][0]["conclusion"], "FAILURE")
        self.assertEqual(state["next_blocker"], "checks_not_successful")
        self.assertFalse(state["merge_ready"])

    def test_clean_pr_is_merge_ready(self):
        state = pr_review_state.state_from_pages(
            repo="base-owner/base-repo",
            pages=[fixture("clean_pr.json")],
        )

        self.assertIsNone(state["next_blocker"])
        self.assertTrue(state["merge_ready"])

    def test_blocked_merge_state_blocks_even_when_mergeable(self):
        state = pr_review_state.state_from_pages(
            repo="base-owner/base-repo",
            pages=[fixture("blocked_merge_state.json")],
        )

        self.assertEqual(state["github_state"]["mergeable"], "MERGEABLE")
        self.assertEqual(state["github_state"]["merge_state"], "BLOCKED")
        self.assertEqual(state["next_blocker"], "merge_state_not_clean")
        self.assertFalse(state["merge_ready"])

    def test_writes_resume_ready_ledger(self):
        state = pr_review_state.state_from_pages(
            repo="base-owner/base-repo",
            pages=[fixture("clean_pr.json")],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = pr_review_state.write_ledger(state, root=Path(temp_dir))
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(saved["schema_version"], 1)
        self.assertIn("external_review_attempts", saved)
        self.assertIn("local_reviews", saved)
        self.assertIn("verification", saved["local_readiness"])
        self.assertIn("review_items", saved)
        self.assertIn("decisions", saved)
        self.assertIn("next_blocker", saved)

    def test_write_ledger_preserves_existing_review_history(self):
        state = pr_review_state.state_from_pages(
            repo="base-owner/base-repo",
            pages=[fixture("clean_pr.json")],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger_dir = root / "base-owner" / "base-repo"
            ledger_dir.mkdir(parents=True)
            ledger_path = ledger_dir / "7.json"
            ledger_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "cycles": {"local_review_count": 1, "external_completed_count": 2, "external_failed_count": 1},
                        "local_readiness": {"verification": [{"command": "cargo test", "status": "passed"}]},
                        "local_reviews": [{"id": "local-1"}],
                        "external_review_attempts": [{"id": "coderabbit-1", "status": "completed"}],
                        "review_items": [{"id": "thread-1", "disposition": "fixed_with_evidence"}],
                        "decisions": [{"id": "decision-1"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            pr_review_state.write_ledger(state, root=root)
            saved = json.loads(ledger_path.read_text(encoding="utf-8"))

        self.assertEqual(saved["cycles"]["external_completed_count"], 2)
        self.assertEqual(saved["local_readiness"]["verification"][0]["command"], "cargo test")
        self.assertEqual(saved["local_reviews"][0]["id"], "local-1")
        self.assertEqual(saved["external_review_attempts"][0]["id"], "coderabbit-1")
        self.assertEqual(saved["review_items"][0]["id"], "thread-1")
        self.assertEqual(saved["decisions"][0]["id"], "decision-1")

    def test_cli_writes_ledger_to_custom_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = pr_review_state.main(
                    [
                        "--repo",
                        "base-owner/base-repo",
                        "--pr",
                        "7",
                        "--fixture",
                        str(FIXTURE_DIR / "clean_pr.json"),
                        "--write-ledger",
                        "--ledger-root",
                        temp_dir,
                    ]
                )
            ledger_path = Path(temp_dir) / "base-owner" / "base-repo" / "7.json"
            ledger_exists = ledger_path.exists()

        self.assertEqual(exit_code, 0)
        self.assertTrue(ledger_exists)


if __name__ == "__main__":
    unittest.main()
