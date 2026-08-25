from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.privacy_age_admission_publisher import (
    APP_ID,
    GitHubClient,
    Publication,
    PublicationError,
    _ResponsePage,
    _classify_existing_runs,
    publish,
)
from scripts.privacy_age_admission_result import (
    AdmissionResultError,
    CHECK_NAME,
    canonical_json_bytes,
    external_id,
    make_result,
    make_snapshot,
    make_state,
    parse_canonical_json,
    parse_external_id,
    PullRequestSnapshot,
    validate_snapshot,
    validate_state,
)
from scripts.privacy_age_pr_snapshot import (
    SnapshotError,
    event_identity,
    main as snapshot_main,
)


BASE = "a" * 40
HEAD = "b" * 40


def snapshot(*, body_sha256: str = "sha256:" + "c" * 64, pull_request: int = 166) -> PullRequestSnapshot:
    return validate_snapshot(make_snapshot(
        repository="nisavid/dotfiles",
        pull_request=pull_request,
        state="open",
        base_ref="main",
        base_commit=BASE,
        head_repository="nisavid/dotfiles",
        head_commit=HEAD,
        body_sha256=body_sha256,
    ))


class AdmissionResultTests(TestCase):
    def test_empty_and_verified_states_are_bound_to_the_snapshot(self) -> None:
        current = snapshot()
        empty = make_result(
            repository="nisavid/dotfiles",
            base_commit=BASE,
            head_commit=HEAD,
            protected_paths=[],
        )
        state = make_state(snapshot=current.as_dict(), result=empty)
        self.assertEqual(validate_state(state)["state"], "verified")
        self.assertEqual(
            external_id(validate_snapshot(validate_state(state)["snapshot"])),  # type: ignore[arg-type]
            external_id(current),
        )

    def test_canonical_parser_rejects_duplicates_and_noncanonical_bytes(self) -> None:
        with self.assertRaises(AdmissionResultError):
            parse_canonical_json(b'{"a":1,"a":2}')
        with self.assertRaises(AdmissionResultError):
            parse_canonical_json(b'{"b":2,"a":1}')
        document = {"a": 1, "b": [True, None]}
        self.assertEqual(
            parse_canonical_json(canonical_json_bytes(document)),
            document,
        )

    def test_snapshot_version_is_closed(self) -> None:
        current = snapshot().as_dict()
        current["version"] = "privacy-age-admission-snapshot/other"
        with self.assertRaises(AdmissionResultError):
            validate_snapshot(current)

    def test_external_identity_round_trips_and_rejects_legacy_data(self) -> None:
        current = snapshot()
        self.assertEqual(parse_external_id(external_id(current)), current)
        with self.assertRaises(AdmissionResultError):
            parse_external_id("legacy")

    def test_failed_state_is_bounded_and_carries_no_result(self) -> None:
        state = make_state(snapshot=snapshot().as_dict(), error_code="verifier_failed")
        self.assertEqual(validate_state(state)["state"], "failed")
        self.assertIsNone(state["result"])
        with self.assertRaises(AdmissionResultError):
            make_state(snapshot=None, result=make_result(
                repository="nisavid/dotfiles",
                base_commit=BASE,
                head_commit=HEAD,
                protected_paths=[],
            ))


class SnapshotIdentityTests(TestCase):
    def test_event_is_only_a_repository_and_pull_request_locator(self) -> None:
        event = {
            "repository": {"full_name": "nisavid/dotfiles"},
            "pull_request": {"number": 166, "base": {"sha": "wrong"}},
        }
        self.assertEqual(event_identity(event, expected_repository="nisavid/dotfiles"), ("nisavid/dotfiles", 166))
        with self.assertRaises(SnapshotError):
            event_identity(event, expected_repository="attacker/dotfiles")

    def test_snapshot_main_uses_pull_request_target_event_only_as_locator(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            event_path = root / "event.json"
            output_path = root / "snapshot.json"
            event_path.write_text(
                json.dumps(
                    {
                        "action": "edited",
                        "repository": {"full_name": "nisavid/dotfiles"},
                        "pull_request": {"number": 166, "base": {"sha": "stale"}},
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"GITHUB_TOKEN": "read-only"}, clear=False), patch(
                "scripts.privacy_age_pr_snapshot.fetch_live_binding",
                return_value=(snapshot().as_dict(), ""),
            ), patch.object(
                sys,
                "argv",
                [
                    "privacy_age_pr_snapshot.py",
                    "--event",
                    os.fspath(event_path),
                    "--output",
                    os.fspath(output_path),
                    "--repository",
                    "nisavid/dotfiles",
                ],
            ):
                self.assertEqual(snapshot_main(), 0)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["pull_request"], 166)


class PublisherReconciliationTests(TestCase):
    def setUp(self) -> None:
        self.current = snapshot()
        self.expected = external_id(self.current)  # type: ignore[arg-type]

    def run_record(self, *, run_id: int = 7, external: str | None = None, app: int = APP_ID, head: str = HEAD) -> dict[str, object]:
        return {
            "id": run_id,
            "name": CHECK_NAME,
            "app": {"id": app},
            "head_sha": head,
            "external_id": self.expected if external is None else external,
            "status": "completed",
            "conclusion": "success",
        }

    def test_exact_run_is_reused_but_legacy_and_duplicates_fail_closed(self) -> None:
        self.assertEqual(
            _classify_existing_runs(
                [self.run_record()],
                snapshot=self.current,
                expected_external_id=self.expected,
                expected_conclusion="success",
            ),
            7,
        )
        prior = snapshot(body_sha256="sha256:" + "d" * 64)
        self.assertEqual(
            _classify_existing_runs(
                [self.run_record(external=external_id(prior))],
                snapshot=self.current,
                expected_external_id=self.expected,
            ),
            7,
        )
        for records in (
            [self.run_record(external="legacy")],
            [self.run_record(), self.run_record(run_id=8)],
            [self.run_record(app=999)],
            [self.run_record(head="c" * 40)],
            [self.run_record() | {"status": "in_progress", "conclusion": None}],
            [self.run_record() | {"conclusion": "failure"}],
        ):
            with self.assertRaises(PublicationError):
                _classify_existing_runs(
                    records,
                    snapshot=self.current,
                    expected_external_id=self.expected,
                    expected_conclusion="success",
                )

    def test_publish_rechecks_before_post_and_reconciles_response(self) -> None:
        publication = Publication(
            snapshot=self.current,
            result=make_result(
                repository="nisavid/dotfiles",
                base_commit=BASE,
                head_commit=HEAD,
                protected_paths=[],
            ),
            conclusion="success",
            failure_code=None,
        )

        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, object | None]] = []

            def list_check_runs(self, *, repository: str, head_commit: str) -> list[dict[str, object]]:
                self.calls.append(("LIST", repository, head_commit))
                if len([call for call in self.calls if call[0] == "LIST"]) == 1:
                    return []
                return [{
                    "id": 9,
                    "name": CHECK_NAME,
                    "app": {"id": APP_ID},
                    "head_sha": HEAD,
                    "external_id": self_expected,
                    "status": "completed",
                    "conclusion": "success",
                }]

            def request(self, method: str, path: str, payload: object | None = None) -> object:
                self.calls.append((method, path, payload))
                return {
                    "id": 9,
                    "name": CHECK_NAME,
                    "app": {"id": APP_ID},
                    "head_sha": HEAD,
                    "external_id": self_expected,
                    "status": "completed",
                    "conclusion": "success",
                }

        self_expected = self.expected
        client = FakeClient()
        with patch(
            "scripts.privacy_age_admission_publisher.fetch_live_snapshot",
            return_value=self.current.as_dict(),
        ), patch(
            "scripts.privacy_age_admission_publisher._now",
            return_value="2026-08-25T00:00:00Z",
        ):
            self.assertEqual(
                publish(
                    client=client,  # type: ignore[arg-type]
                    publication=publication,
                    final_snapshot=self.current,
                    read_api_root="https://api.github.com",
                    read_token="read-only",
                ),
                9,
            )
        self.assertTrue(any(call[0] == "POST" for call in client.calls))
        payload = next(call[2] for call in client.calls if call[0] == "POST")
        self.assertEqual(payload["external_id"], self.expected)  # type: ignore[index]

    def test_publish_aborts_when_final_snapshot_changes(self) -> None:
        publication = Publication(
            snapshot=self.current,
            result=None,
            conclusion="failure",
            failure_code="verifier_failed",
        )

        class NoWriteClient:
            def list_check_runs(self, **_: object) -> list[dict[str, object]]:
                return []

            def request(self, *_: object, **__: object) -> object:
                self.called = True
                return {}

        client = NoWriteClient()
        changed = snapshot(body_sha256="sha256:" + "d" * 64)
        with patch(
            "scripts.privacy_age_admission_publisher.fetch_live_snapshot",
            return_value=changed.as_dict(),
        ), self.assertRaises(PublicationError):
            publish(
                client=client,  # type: ignore[arg-type]
                publication=publication,
                final_snapshot=self.current,
                read_api_root="https://api.github.com",
                read_token="read-only",
            )
        self.assertFalse(hasattr(client, "called"))

    def test_publish_supersedes_one_prior_same_pr_head_identity(self) -> None:
        publication = Publication(
            snapshot=self.current,
            result=make_result(
                repository="nisavid/dotfiles",
                base_commit=BASE,
                head_commit=HEAD,
                protected_paths=[],
            ),
            conclusion="success",
            failure_code=None,
        )
        prior = snapshot(body_sha256="sha256:" + "d" * 64)

        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, object | None]] = []
                self.list_count = 0

            def list_check_runs(self, *, repository: str, head_commit: str) -> list[dict[str, object]]:
                self.list_count += 1
                self.calls.append(("LIST", repository, head_commit))
                external = external_id(prior) if self.list_count == 1 else self_expected
                return [{
                    "id": 11,
                    "name": CHECK_NAME,
                    "app": {"id": APP_ID},
                    "head_sha": HEAD,
                    "external_id": external,
                    "status": "completed",
                    "conclusion": "success",
                }]

            def request(self, method: str, path: str, payload: object | None = None) -> object:
                self.calls.append((method, path, payload))
                return {
                    "id": 11,
                    "name": CHECK_NAME,
                    "app": {"id": APP_ID},
                    "head_sha": HEAD,
                    "external_id": self_expected,
                    "status": "completed",
                    "conclusion": "success",
                }

            def get_check_run(self, *, repository: str, run_id: int) -> dict[str, object]:
                self.calls.append(("GET", repository, run_id))
                return {
                    "id": run_id,
                    "name": CHECK_NAME,
                    "app": {"id": APP_ID},
                    "head_sha": HEAD,
                    "external_id": external_id(prior),
                    "status": "completed",
                    "conclusion": "success",
                }

        self_expected = self.expected
        client = FakeClient()
        with patch(
            "scripts.privacy_age_admission_publisher.fetch_live_snapshot",
            return_value=self.current.as_dict(),
        ), patch(
            "scripts.privacy_age_admission_publisher._now",
            return_value="2026-08-25T00:00:00Z",
        ):
            self.assertEqual(
                publish(
                    client=client,  # type: ignore[arg-type]
                    publication=publication,
                    final_snapshot=self.current,
                    read_api_root="https://api.github.com",
                    read_token="read-only",
                ),
                11,
            )
        patch_call = next(call for call in client.calls if call[0] == "PATCH")
        self.assertEqual(patch_call[2]["external_id"], self.expected)  # type: ignore[index]
        self.assertNotIn("head_sha", patch_call[2])  # type: ignore[operator]

    def test_publish_aborts_if_selected_run_identity_changes_before_update(self) -> None:
        publication = Publication(
            snapshot=self.current,
            result=make_result(
                repository="nisavid/dotfiles",
                base_commit=BASE,
                head_commit=HEAD,
                protected_paths=[],
            ),
            conclusion="success",
            failure_code=None,
        )
        prior = snapshot(body_sha256="sha256:" + "d" * 64)

        class ChangedClient:
            def __init__(self) -> None:
                self.writes = 0

            def list_check_runs(self, **_: object) -> list[dict[str, object]]:
                return [{
                    "id": 11,
                    "name": CHECK_NAME,
                    "app": {"id": APP_ID},
                    "head_sha": HEAD,
                    "external_id": external_id(prior),
                    "status": "completed",
                    "conclusion": "success",
                }]

            def get_check_run(self, **_: object) -> dict[str, object]:
                return {
                    "id": 11,
                    "name": CHECK_NAME,
                    "app": {"id": APP_ID},
                    "head_sha": HEAD,
                    "external_id": self_expected,
                    "status": "completed",
                    "conclusion": "success",
                }

            def request(self, method: str, *_: object, **__: object) -> object:
                if method in {"POST", "PATCH"}:
                    self.writes += 1
                return {}

        self_expected = self.expected
        client = ChangedClient()
        with patch(
            "scripts.privacy_age_admission_publisher.fetch_live_snapshot",
            return_value=self.current.as_dict(),
        ), self.assertRaises(PublicationError):
            publish(
                client=client,  # type: ignore[arg-type]
                publication=publication,
                final_snapshot=self.current,
                read_api_root="https://api.github.com",
                read_token="read-only",
            )
        self.assertEqual(client.writes, 0)

    def test_check_run_listing_follows_valid_link_pagination(self) -> None:
        client = GitHubClient(api_root="https://api.github.com", token="checks")
        first = self.run_record(run_id=11)
        second = self.run_record(run_id=12)
        next_url = (
            "https://api.github.com/repos/nisavid/dotfiles/commits/"
            + HEAD
            + "/check-runs?check_name=Owner-signed+age+admission&filter=all&per_page=100&page=2"
        )
        with patch.object(
            client,
            "_request_page",
            side_effect=[
                _ResponsePage(
                    {"total_count": 2, "check_runs": [first]},
                    {"link": f'<{next_url}>; rel="next"'},
                ),
                _ResponsePage(
                    {"total_count": 2, "check_runs": [second]},
                    {},
                ),
            ],
        ) as request_page:
            self.assertEqual(
                [run["id"] for run in client.list_check_runs(
                    repository="nisavid/dotfiles", head_commit=HEAD
                )],
                [11, 12],
            )
        self.assertEqual(request_page.call_count, 2)
        first_url = request_page.call_args_list[0].args[1]
        self.assertIn("check_name=Owner-signed+age+admission", first_url)
        self.assertIn("filter=all", first_url)
        self.assertEqual(request_page.call_args_list[1].args[1], next_url)

    def test_check_run_listing_fails_closed_on_incomplete_pagination(self) -> None:
        client = GitHubClient(api_root="https://api.github.com", token="checks")
        with patch.object(
            client,
            "_request_page",
            return_value=_ResponsePage(
                {"total_count": 2, "check_runs": [self.run_record()]},
                {},
            ),
        ), self.assertRaises(PublicationError):
            client.list_check_runs(repository="nisavid/dotfiles", head_commit=HEAD)
