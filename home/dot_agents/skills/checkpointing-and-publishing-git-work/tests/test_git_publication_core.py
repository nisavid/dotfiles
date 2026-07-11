import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from git_publication.core import PublicationRequest, RepositorySnapshot, plan_publication


A = "a" * 40
B = "b" * 40
C = "c" * 40


def request(**overrides):
    values = {
        "schema_version": 1,
        "start_head": A,
        "source_sha": B,
        "task_owned_commits": frozenset({B}),
        "adopted_commits": frozenset(),
        "removal_authorized_commits": frozenset(),
        "explicit_destination": None,
        "allow_create": False,
        "creation_base_ref": None,
    }
    values.update(overrides)
    return PublicationRequest(**values)


def snapshot(**overrides):
    values = {
        "remote": "upstream",
        "ref": "refs/heads/topic",
        "endpoint_fingerprint": "sha256:endpoint",
        "config_digest": "sha256:config",
        "target_present": True,
        "target_sha": A,
        "outgoing_shas": (B,),
        "target_only_shas": (),
        "target_is_ancestor": True,
        "start_is_ancestor": True,
        "start_advertised": True,
        "creation_base_sha": None,
        "creation_base_is_ancestor": None,
        "creation_base_to_start_shas": (),
    }
    values.update(overrides)
    return RepositorySnapshot(**values)


class CorePlanningTests(unittest.TestCase):
    def test_ready_fast_forward_uses_immutable_source_and_exact_lease(self):
        result = plan_publication(request(), snapshot())

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["source_sha"], B)
        self.assertEqual(
            result["push"]["argv"],
            [
                "git",
                "push",
                "--no-follow-tags",
                "--recurse-submodules=check",
                f"--force-with-lease=refs/heads/topic:{A}",
                "--",
                "upstream",
                f"{B}:refs/heads/topic",
            ],
        )

    def test_verified_has_no_push(self):
        result = plan_publication(request(), snapshot(target_sha=B, outgoing_shas=()))
        self.assertEqual(result["status"], "verified")
        self.assertIsNone(result["push"])

    def test_unowned_outgoing_commit_blocks(self):
        result = plan_publication(request(), snapshot(outgoing_shas=(B, C)))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "OUTGOING_COMMITS_NOT_OWNED_OR_ADOPTED")

    def test_adopted_outgoing_commit_is_allowed(self):
        result = plan_publication(
            request(adopted_commits=frozenset({C})), snapshot(outgoing_shas=(B, C))
        )
        self.assertEqual(result["status"], "ready")

    def test_divergence_needs_reconciliation_without_exact_removal_authorization(self):
        result = plan_publication(
            request(), snapshot(target_only_shas=(C,), target_is_ancestor=False)
        )
        self.assertEqual(result["status"], "needs_reconciliation")
        self.assertTrue(result["rewrite_required"])

    def test_authorized_rewrite_uses_exact_lease(self):
        result = plan_publication(
            request(removal_authorized_commits=frozenset({C})),
            snapshot(target_only_shas=(C,), target_is_ancestor=False),
        )
        self.assertEqual(result["status"], "ready")
        self.assertIn(f"--force-with-lease=refs/heads/topic:{A}", result["push"]["argv"])

    def test_absent_target_requires_creation_authorization(self):
        result = plan_publication(
            request(), snapshot(target_present=False, target_sha=None, target_is_ancestor=False)
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "TARGET_ABSENT_CREATION_NOT_ALLOWED")

    def test_absent_advertised_start_uses_expected_absent_lease(self):
        result = plan_publication(
            request(allow_create=True),
            snapshot(target_present=False, target_sha=None, target_is_ancestor=False),
        )
        self.assertEqual(result["status"], "ready")
        self.assertIn("--force-with-lease=refs/heads/topic:", result["push"]["argv"])

    def test_creation_base_requires_every_base_to_start_commit_adopted(self):
        result = plan_publication(
            request(allow_create=True, creation_base_ref="refs/heads/main"),
            snapshot(
                target_present=False,
                target_sha=None,
                target_is_ancestor=False,
                start_advertised=False,
                creation_base_sha=C,
                creation_base_is_ancestor=True,
                creation_base_to_start_shas=(A,),
            ),
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][-1]["code"], "CREATION_BASE_TO_START_COMMITS_NOT_ADOPTED")

    def test_creation_base_with_adoption_is_ready(self):
        result = plan_publication(
            request(
                allow_create=True,
                creation_base_ref="refs/heads/main",
                adopted_commits=frozenset({A}),
            ),
            snapshot(
                target_present=False,
                target_sha=None,
                target_is_ancestor=False,
                start_advertised=False,
                creation_base_sha=C,
                creation_base_is_ancestor=True,
                creation_base_to_start_shas=(A,),
            ),
        )
        self.assertEqual(result["status"], "ready")


if __name__ == "__main__":
    unittest.main()
