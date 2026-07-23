from __future__ import annotations

import hashlib
import importlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = (
    Path(__file__).parents[1]
    / "home/dot_agents/skills/publishing-reviewable-prs/scripts"
)
sys.path.insert(0, str(SCRIPTS))
STATE = importlib.import_module("reviewable_pr_state")


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CREATE = load("create_reviewable_pr", "create_reviewable_pr.py")
UPDATE = load("update_reviewable_pr", "update_reviewable_pr.py")


class ReviewablePrStateTests(unittest.TestCase):
    def test_open_pr_list_uses_unqualified_branch_and_defers_owner_matching(
        self,
    ) -> None:
        completed = subprocess.CompletedProcess([], 0, "[]", "")
        with mock.patch.object(STATE, "run", return_value=completed) as run:
            self.assertEqual(STATE.open_prs("acme/app", "main", "ivan:widget"), [])

        arguments = run.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--head") + 1], "widget")


class ReviewablePrFixture(unittest.TestCase):
    repository = "acme/app"
    base = "main"
    head = "ivan:widget"
    head_owner = "ivan"
    base_oid = "a" * 40
    head_oid = "b" * 40
    title = "feat: widget"
    pr_number = 42
    url = "https://github.com/acme/app/pull/42"
    nonce = "nonce-42"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.template_path = Path(self.temporary_directory.name) / "body.md"
        self.template = (
            "<details>\n"
            f"https://github.com/acme/app/pull/{CREATE.PR_NUMBER_TOKEN}/files\n"
            "</details>\n"
        )
        self.template_path.write_text(self.template, encoding="utf-8")
        self.body = self.template.replace(CREATE.PR_NUMBER_TOKEN, str(self.pr_number))
        self.transport_body = CREATE._transport_body(self.nonce)

    @property
    def expected(self):
        return CREATE.ExpectedIdentity(
            repository=self.repository,
            pr_number=self.pr_number,
            base=self.base,
            base_oid=self.base_oid,
            head=self.head,
            head_oid=self.head_oid,
            head_owner=self.head_owner,
        )

    def stored(
        self,
        *,
        body: str | None = None,
        title: str | None = None,
        is_draft: bool = True,
        state: str = "OPEN",
        **overrides: object,
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "number": self.pr_number,
            "url": self.url,
            "title": self.title if title is None else title,
            "body": self.body if body is None else body,
            "baseRefName": self.base,
            "baseRefOid": self.base_oid,
            "headRefName": "widget",
            "headRefOid": self.head_oid,
            "headRepositoryOwner": {"login": self.head_owner},
            "isDraft": is_draft,
            "state": state,
        }
        value.update(overrides)
        return value

    def transport(self, **overrides: object) -> dict[str, object]:
        return self.stored(body=self.transport_body, **overrides)

    def publish(self):
        return CREATE.publish(
            repository=self.repository,
            base=self.base,
            base_oid=self.base_oid,
            head=self.head,
            head_oid=self.head_oid,
            head_owner=self.head_owner,
            title=self.title,
            template_path=self.template_path,
        )


class CreateReviewablePrTests(ReviewablePrFixture):
    def test_create_always_drafts_after_empty_exact_preflight(self) -> None:
        completed = subprocess.CompletedProcess([], 0, self.url, "")
        with (
            mock.patch.object(CREATE, "_matching_head_prs", return_value=[]),
            mock.patch.object(CREATE, "_run", return_value=completed) as run,
        ):
            result = CREATE._create(
                repository=self.repository,
                base=self.base,
                base_oid=self.base_oid,
                head=self.head,
                head_oid=self.head_oid,
                head_owner=self.head_owner,
                title=self.title,
                nonce=self.nonce,
            )
        self.assertEqual(result, (self.pr_number, self.url))
        self.assertIn("--draft", run.call_args.args[0])

    def test_stops_before_create_when_exact_head_base_pr_exists(self) -> None:
        with (
            mock.patch.object(
                CREATE, "_matching_head_prs", return_value=[self.stored()]
            ),
            mock.patch.object(CREATE, "_run") as run,
        ):
            with self.assertRaisesRegex(CREATE.PublicationError, "already exists"):
                CREATE._create(
                    repository=self.repository,
                    base=self.base,
                    base_oid=self.base_oid,
                    head=self.head,
                    head_oid=self.head_oid,
                    head_owner=self.head_owner,
                    title=self.title,
                    nonce=self.nonce,
                )
        run.assert_not_called()

    def test_recovers_unique_nonce_draft_after_ambiguous_create_error(self) -> None:
        with (
            mock.patch.object(
                CREATE, "_matching_head_prs", side_effect=[[], [self.transport()]]
            ),
            mock.patch.object(
                CREATE, "_run", side_effect=CREATE.PublicationError("network lost")
            ),
        ):
            result = CREATE._create(
                repository=self.repository,
                base=self.base,
                base_oid=self.base_oid,
                head=self.head,
                head_oid=self.head_oid,
                head_owner=self.head_owner,
                title=self.title,
                nonce=self.nonce,
            )
        self.assertEqual(result, (self.pr_number, self.url))

    def test_rejects_recovery_without_exact_nonce_and_oids(self) -> None:
        wrong = self.transport(headRefOid="c" * 40)
        with (
            mock.patch.object(CREATE, "_matching_head_prs", side_effect=[[], [wrong]]),
            mock.patch.object(
                CREATE, "_run", side_effect=CREATE.PublicationError("network lost")
            ),
        ):
            with self.assertRaisesRegex(CREATE.PublicationError, "ambiguous"):
                CREATE._create(
                    repository=self.repository,
                    base=self.base,
                    base_oid=self.base_oid,
                    head=self.head,
                    head_oid=self.head_oid,
                    head_owner=self.head_owner,
                    title=self.title,
                    nonce=self.nonce,
                )

    def test_recovers_after_successful_create_returns_malformed_output(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "created", "")
        with (
            mock.patch.object(
                CREATE, "_matching_head_prs", side_effect=[[], [self.transport()]]
            ),
            mock.patch.object(CREATE, "_run", return_value=completed),
        ):
            result = CREATE._create(
                repository=self.repository,
                base=self.base,
                base_oid=self.base_oid,
                head=self.head,
                head_oid=self.head_oid,
                head_owner=self.head_owner,
                title=self.title,
                nonce=self.nonce,
            )
        self.assertEqual(result, (self.pr_number, self.url))

    def test_installs_canonical_body_with_one_mutation_and_final_read(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        with (
            mock.patch.object(CREATE, "_validate"),
            mock.patch.object(CREATE, "_new_nonce", return_value=self.nonce),
            mock.patch.object(CREATE, "_create", return_value=(42, self.url)),
            mock.patch.object(CREATE, "_run", return_value=completed) as run,
            mock.patch.object(
                CREATE,
                "_stored_pr",
                side_effect=[self.transport(), self.transport(), self.stored()],
            ) as reads,
        ):
            result = self.publish()
        self.assertEqual(result, self.stored())
        self.assertEqual(run.call_count, 1)
        self.assertEqual(reads.call_count, 3)

    def test_edit_error_uses_final_read_to_accept_ambiguous_success(self) -> None:
        with (
            mock.patch.object(CREATE, "_validate"),
            mock.patch.object(CREATE, "_new_nonce", return_value=self.nonce),
            mock.patch.object(CREATE, "_create", return_value=(42, self.url)),
            mock.patch.object(
                CREATE, "_run", side_effect=CREATE.PublicationError("lost response")
            ) as run,
            mock.patch.object(
                CREATE,
                "_stored_pr",
                side_effect=[self.transport(), self.transport(), self.stored()],
            ),
        ):
            result = self.publish()
        self.assertEqual(result, self.stored())
        self.assertEqual(run.call_count, 1)

    def test_edit_failure_is_not_retried_or_rolled_back(self) -> None:
        with (
            mock.patch.object(CREATE, "_validate"),
            mock.patch.object(CREATE, "_new_nonce", return_value=self.nonce),
            mock.patch.object(CREATE, "_create", return_value=(42, self.url)),
            mock.patch.object(
                CREATE, "_run", side_effect=CREATE.PublicationError("failed")
            ) as run,
            mock.patch.object(
                CREATE,
                "_stored_pr",
                side_effect=[self.transport(), self.transport(), self.transport()],
            ),
        ):
            with self.assertRaisesRegex(CREATE.PublicationError, "no automatic retry"):
                self.publish()
        self.assertEqual(run.call_count, 1)

    def test_concurrent_state_blocks_mutation_or_retry(self) -> None:
        concurrent = self.stored(title="reviewer edit", body="reviewer body")
        with (
            mock.patch.object(CREATE, "_validate"),
            mock.patch.object(CREATE, "_new_nonce", return_value=self.nonce),
            mock.patch.object(CREATE, "_create", return_value=(42, self.url)),
            mock.patch.object(CREATE, "_run") as run,
            mock.patch.object(
                CREATE, "_stored_pr", side_effect=[self.transport(), concurrent]
            ),
        ):
            with self.assertRaisesRegex(CREATE.PublicationError, "no longer has"):
                self.publish()
        run.assert_not_called()

    def test_requires_qualified_head_before_validation_or_create(self) -> None:
        with (
            mock.patch.object(CREATE, "_validate") as validate,
            mock.patch.object(CREATE, "_create") as create,
        ):
            with self.assertRaisesRegex(CREATE.PublicationError, "OWNER:BRANCH"):
                CREATE.publish(
                    repository=self.repository,
                    base=self.base,
                    base_oid=self.base_oid,
                    head="widget",
                    head_oid=self.head_oid,
                    head_owner=self.head_owner,
                    title=self.title,
                    template_path=self.template_path,
                )
        validate.assert_not_called()
        create.assert_not_called()


class UpdateReviewablePrTests(ReviewablePrFixture):
    def digest(self, value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def desired_body_path(self) -> Path:
        path = Path(self.temporary_directory.name) / "desired.md"
        path.write_text(self.body + "updated\n", encoding="utf-8")
        return path

    def test_text_update_has_exact_preflight_one_write_and_final_read(self) -> None:
        desired_path = self.desired_body_path()
        desired = desired_path.read_text()
        after = self.stored(title="feat: updated", body=desired)
        with (
            mock.patch.object(UPDATE, "_validate_body"),
            mock.patch.object(
                UPDATE, "_stored_pr", side_effect=[self.stored(), after]
            ) as reads,
            mock.patch.object(
                UPDATE,
                "_run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run,
        ):
            result = UPDATE.update_text(
                expected=self.expected,
                expected_title_sha256=self.digest(self.title),
                expected_body_sha256=self.digest(self.body),
                expected_draft=True,
                title="feat: updated",
                body_path=desired_path,
            )
        self.assertEqual(result, after)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(reads.call_count, 2)

    def test_text_update_accepts_exact_noncanonical_preimage(self) -> None:
        legacy_body = "Legacy PR body without change navigation.\n"
        desired_path = self.desired_body_path()
        desired = desired_path.read_text()
        after = self.stored(title="feat: updated", body=desired)
        with (
            mock.patch.object(UPDATE, "_validate_body") as validate,
            mock.patch.object(
                UPDATE,
                "_stored_pr",
                side_effect=[self.stored(body=legacy_body), after],
            ),
            mock.patch.object(
                UPDATE,
                "_run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ),
        ):
            result = UPDATE.update_text(
                expected=self.expected,
                expected_title_sha256=self.digest(self.title),
                expected_body_sha256=self.digest(legacy_body),
                expected_draft=True,
                title="feat: updated",
                body_path=desired_path,
            )
        self.assertEqual(result, after)
        validate.assert_called_once_with(desired, self.repository, self.pr_number)

    def test_text_update_publishes_validated_snapshot(self) -> None:
        desired_path = self.desired_body_path()
        desired = desired_path.read_text()
        after = self.stored(body=desired)

        def mutate_source_after_snapshot(arguments: list[str], **_: object):
            body_file = Path(arguments[arguments.index("--body-file") + 1])
            self.assertNotEqual(body_file, desired_path)
            self.assertEqual(body_file.read_text(encoding="utf-8"), desired)
            desired_path.write_text("changed after validation\n", encoding="utf-8")
            return subprocess.CompletedProcess([], 0, "", "")

        with (
            mock.patch.object(UPDATE, "_validate_body"),
            mock.patch.object(UPDATE, "_stored_pr", side_effect=[self.stored(), after]),
            mock.patch.object(UPDATE, "_run", side_effect=mutate_source_after_snapshot),
        ):
            result = UPDATE.update_text(
                expected=self.expected,
                expected_title_sha256=self.digest(self.title),
                expected_body_sha256=self.digest(self.body),
                expected_draft=True,
                title=self.title,
                body_path=desired_path,
            )
        self.assertEqual(result, after)

    def test_text_preimage_drift_stops_before_write(self) -> None:
        with (
            mock.patch.object(UPDATE, "_validate_body"),
            mock.patch.object(UPDATE, "_stored_pr", return_value=self.stored()),
            mock.patch.object(UPDATE, "_run") as run,
        ):
            with self.assertRaisesRegex(UPDATE.PublicationError, "preimage changed"):
                UPDATE.update_text(
                    expected=self.expected,
                    expected_title_sha256="c" * 64,
                    expected_body_sha256=self.digest(self.body),
                    expected_draft=True,
                    title=self.title,
                    body_path=self.desired_body_path(),
                )
        run.assert_not_called()

    def test_text_command_error_accepts_only_verified_ambiguous_success(self) -> None:
        desired_path = self.desired_body_path()
        after = self.stored(body=desired_path.read_text())
        with (
            mock.patch.object(UPDATE, "_validate_body"),
            mock.patch.object(UPDATE, "_stored_pr", side_effect=[self.stored(), after]),
            mock.patch.object(
                UPDATE, "_run", side_effect=UPDATE.PublicationError("lost response")
            ) as run,
        ):
            result = UPDATE.update_text(
                expected=self.expected,
                expected_title_sha256=self.digest(self.title),
                expected_body_sha256=self.digest(self.body),
                expected_draft=True,
                title=self.title,
                body_path=desired_path,
            )
        self.assertEqual(result, after)
        self.assertEqual(run.call_count, 1)

    def test_text_ambiguous_drift_is_not_retried_or_rolled_back(self) -> None:
        desired_path = self.desired_body_path()
        concurrent = self.stored(title="reviewer edit", body="reviewer body")
        with (
            mock.patch.object(UPDATE, "_validate_body"),
            mock.patch.object(
                UPDATE, "_stored_pr", side_effect=[self.stored(), concurrent]
            ),
            mock.patch.object(
                UPDATE,
                "_run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run,
        ):
            with self.assertRaisesRegex(
                UPDATE.PublicationError, "no retry or rollback"
            ):
                UPDATE.update_text(
                    expected=self.expected,
                    expected_title_sha256=self.digest(self.title),
                    expected_body_sha256=self.digest(self.body),
                    expected_draft=True,
                    title=self.title,
                    body_path=desired_path,
                )
        self.assertEqual(run.call_count, 1)

    def test_ready_uses_exact_preimage_and_final_read(self) -> None:
        with (
            mock.patch.object(UPDATE, "_validate_body"),
            mock.patch.object(
                UPDATE,
                "_stored_pr",
                side_effect=[
                    self.stored(),
                    self.stored(),
                    self.stored(is_draft=False),
                ],
            ),
            mock.patch.object(
                UPDATE, "_run", side_effect=UPDATE.PublicationError("lost response")
            ) as run,
        ):
            result = UPDATE.mark_ready(
                expected=self.expected,
                expected_title_sha256=self.digest(self.title),
                expected_body_sha256=self.digest(self.body),
            )
        self.assertFalse(result["isDraft"])
        self.assertEqual(run.call_count, 1)

    def test_ready_rechecks_exact_preimage_after_body_validation(self) -> None:
        concurrent = self.stored(title="reviewer edit", body="reviewer body")
        with (
            mock.patch.object(UPDATE, "_validate_body"),
            mock.patch.object(
                UPDATE, "_stored_pr", side_effect=[self.stored(), concurrent]
            ) as reads,
            mock.patch.object(UPDATE, "_run") as run,
        ):
            with self.assertRaisesRegex(UPDATE.PublicationError, "preimage changed"):
                UPDATE.mark_ready(
                    expected=self.expected,
                    expected_title_sha256=self.digest(self.title),
                    expected_body_sha256=self.digest(self.body),
                )
        self.assertEqual(reads.call_count, 2)
        run.assert_not_called()

    def test_ready_rejects_noncanonical_live_body_before_mutation(self) -> None:
        legacy_body = "Legacy PR body without change navigation.\n"
        with (
            mock.patch.object(
                UPDATE, "_stored_pr", return_value=self.stored(body=legacy_body)
            ),
            mock.patch.object(
                UPDATE,
                "_validate_body",
                side_effect=UPDATE.PublicationError("body is noncanonical"),
            ),
            mock.patch.object(UPDATE, "_run") as run,
        ):
            with self.assertRaisesRegex(UPDATE.PublicationError, "noncanonical"):
                UPDATE.mark_ready(
                    expected=self.expected,
                    expected_title_sha256=self.digest(self.title),
                    expected_body_sha256=self.digest(legacy_body),
                )
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
