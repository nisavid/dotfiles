import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
CLI = SCRIPTS / "plan_git_publication.py"
sys.path.insert(0, str(SCRIPTS))

import git_publication.adapter as adapter
from git_publication.adapter import MalformedRequest, parse_request, plan_repository


def git(repo, *args, env=None):
    merged = os.environ.copy()
    merged.update({"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com"})
    merged.update({"GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"})
    if env:
        merged.update(env)
    return subprocess.run(
        ["git", *args], cwd=repo, env=merged, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=True
    ).stdout.strip()


def commit(repo, name):
    (Path(repo) / name).write_text(name, encoding="utf-8")
    git(repo, "add", "--", name)
    git(repo, "commit", "-m", name)
    return git(repo, "rev-parse", "HEAD")


def raw_request(start, source, **overrides):
    value = {
        "schema_version": 1,
        "start_head": start,
        "source_sha": source,
        "task_owned_commits": [source] if source != start else [],
        "adopted_commits": [],
        "removal_authorized_commits": [],
        "explicit_destination": {"remote": "publish", "ref": "refs/heads/topic"},
        "allow_create": False,
        "creation_base_ref": None,
    }
    value.update(overrides)
    return value


class RequestTests(unittest.TestCase):
    def test_rejects_missing_extra_and_short_sha_fields(self):
        complete = raw_request("a" * 40, "b" * 40)
        for bad in (
            {key: value for key, value in complete.items() if key != "source_sha"},
            dict(complete, extra=True),
            dict(complete, source_sha="deadbeef"),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(MalformedRequest):
                    parse_request(bad)

    def test_rejects_option_injection_but_allows_leading_dash_remote(self):
        complete = raw_request("a" * 40, "b" * 40)
        with self.assertRaises(MalformedRequest):
            parse_request(dict(complete, explicit_destination={"remote": "bad\nname", "ref": "refs/heads/x"}))
        parsed = parse_request(
            dict(complete, explicit_destination={"remote": "-publish", "ref": "refs/heads/x"})
        )
        self.assertEqual(parsed.explicit_destination["remote"], "-publish")
        with self.assertRaises(MalformedRequest):
            parse_request(
                dict(complete, explicit_destination={"remote": "publish", "ref": "refs/heads/x:refs/heads/y"})
            )

    def test_credential_bearing_endpoint_never_enters_transport_argv(self):
        endpoint = "https://user:secret@example.invalid/repository"

        class RecordingRepository:
            def __init__(self):
                self.args = None
                self.env_overrides = None

            def run(self, args, check=True, allowed=(), env_overrides=None):
                self.args = args
                self.env_overrides = env_overrides
                return subprocess.CompletedProcess(["git", *args], 0, "", "")

        repo = RecordingRepository()
        adapter._run_endpoint(repo, endpoint, ["ls-remote", "--heads"])

        self.assertNotIn(endpoint, repo.args)
        self.assertNotIn("secret", " ".join(repo.args))
        self.assertEqual(repo.env_overrides, {"CODEX_CHECKPOINTING_ENDPOINT": endpoint})

    def test_remote_push_selection_and_digest_share_one_config_snapshot(self):
        class ChangingConfigRepository:
            def __init__(self):
                self.remote_push_reads = 0

            def output(self, args, allowed=()):
                if args == ["remote"]:
                    return "publish"
                if args == ["symbolic-ref", "-q", "HEAD"]:
                    return "refs/heads/topic"
                if args[0] == "for-each-ref":
                    return "publish\x00refs/heads/topic"
                raise AssertionError(args)

            def config_all(self, key):
                values = {
                    "branch.topic.pushRemote": ["publish"],
                    "remote.pushDefault": [],
                    "push.default": ["simple"],
                }
                if key == "remote.publish.push":
                    self.remote_push_reads += 1
                    return [
                        "refs/heads/topic"
                        if self.remote_push_reads == 1
                        else "refs/heads/topic:refs/heads/changed"
                    ]
                return values[key]

        repo = ChangingConfigRepository()
        request = parse_request(
            raw_request("a" * 40, "b" * 40, explicit_destination=None)
        )

        _, ref, selection = adapter._resolve_destination(repo, request)

        self.assertEqual(ref, "refs/heads/topic")
        self.assertEqual(selection["remote_push"], ["refs/heads/topic"])
        self.assertEqual(repo.remote_push_reads, 1)


class RepositoryPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.remote = root / "remote.git"
        self.repo = root / "repo"
        git(root, "init", "--bare", str(self.remote))
        git(root, "init", "-b", "topic", str(self.repo))
        self.start = commit(self.repo, "base")
        git(self.repo, "remote", "add", "publish", str(self.remote))
        git(self.repo, "push", "publish", f"{self.start}:refs/heads/topic")

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, request):
        return plan_repository(self.repo, request)

    def test_existing_fast_forward_and_terminal_verified(self):
        source = commit(self.repo, "change")
        result = self.plan(raw_request(self.start, source))
        self.assertEqual(result["status"], "ready")
        self.assertIn(f"--force-with-lease=refs/heads/topic:{self.start}", result["push"]["argv"])
        self.assertEqual(result["source_sha"], source)

        git(self.repo, *result["push"]["argv"][1:])
        verified = self.plan(raw_request(self.start, source))
        self.assertEqual(verified["status"], "verified")
        self.assertIsNone(verified["push"])

    def test_source_sha_is_immutable_when_head_moves(self):
        source = commit(self.repo, "change")
        later = commit(self.repo, "later")
        result = self.plan(raw_request(self.start, source))
        self.assertEqual(result["status"], "ready")
        self.assertIn(f"{source}:refs/heads/topic", result["push"]["argv"])
        self.assertNotIn(f"{later}:refs/heads/topic", result["push"]["argv"])

    def test_absent_target_requires_allow_create_and_advertised_start(self):
        source = commit(self.repo, "change")
        request = raw_request(
            self.start,
            source,
            explicit_destination={"remote": "publish", "ref": "refs/heads/new"},
        )
        self.assertEqual(self.plan(request)["status"], "blocked")
        result = self.plan(dict(request, allow_create=True))
        self.assertEqual(result["status"], "ready")
        self.assertIn("--force-with-lease=refs/heads/new:", result["push"]["argv"])

    def test_non_explicit_push_remote_and_remote_push_must_agree_with_default(self):
        source = commit(self.repo, "change")
        git(self.repo, "config", "branch.topic.pushRemote", "publish")
        git(self.repo, "config", "branch.topic.remote", "publish")
        git(self.repo, "config", "branch.topic.merge", "refs/heads/topic")
        request = raw_request(self.start, source, explicit_destination=None)
        self.assertEqual(self.plan(request)["destination"]["ref"], "refs/heads/topic")

        git(self.repo, "config", "remote.publish.push", "refs/heads/topic:refs/heads/other")
        blocked = self.plan(request)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reasons"][0]["code"], "PUSH_TARGET_CONFLICT")

    def test_push_remote_diverging_from_upstream_blocks_simple_default(self):
        other = Path(self.temp.name) / "other.git"
        git(Path(self.temp.name), "init", "--bare", str(other))
        git(self.repo, "remote", "add", "other", str(other))
        git(self.repo, "config", "branch.topic.remote", "publish")
        git(self.repo, "config", "branch.topic.merge", "refs/heads/topic")
        git(self.repo, "config", "branch.topic.pushRemote", "other")
        source = commit(self.repo, "change")

        result = self.plan(raw_request(self.start, source, explicit_destination=None))

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "PUSH_DEFAULT_AMBIGUOUS")

    def test_fetch_and_push_url_divergence_uses_push_endpoint(self):
        push_remote = Path(self.temp.name) / "push.git"
        git(Path(self.temp.name), "init", "--bare", str(push_remote))
        git(self.repo, "push", str(push_remote), f"{self.start}:refs/heads/topic")
        git(self.repo, "remote", "set-url", "--push", "publish", str(push_remote))
        source = commit(self.repo, "change")

        result = self.plan(raw_request(self.start, source))

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["target"]["sha"], self.start)
        self.assertNotIn(str(push_remote), json.dumps(result))

    def test_narrow_fetch_refspec_does_not_hide_push_target(self):
        git(self.repo, "config", "--unset-all", "remote.publish.fetch")
        git(self.repo, "config", "remote.publish.fetch", "+refs/heads/main:refs/remotes/publish/main")
        source = commit(self.repo, "change")
        result = self.plan(raw_request(self.start, source))
        self.assertEqual(result["status"], "ready")

    def test_leading_dash_remote_is_safe_after_option_terminator(self):
        git(self.repo, "config", "remote.-publish.url", str(self.remote))
        source = commit(self.repo, "change")
        request = raw_request(
            self.start,
            source,
            explicit_destination={"remote": "-publish", "ref": "refs/heads/topic"},
        )
        result = self.plan(request)
        self.assertEqual(result["status"], "ready")
        argv = result["push"]["argv"]
        self.assertEqual(argv[argv.index("--") + 1], "-publish")

    def test_multiple_push_urls_block_and_raw_urls_are_never_output(self):
        source = commit(self.repo, "change")
        git(self.repo, "remote", "set-url", "--add", "--push", "publish", "https://user:secret@example.invalid/repo")
        result = self.plan(raw_request(self.start, source))
        serialized = json.dumps(result)
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("secret", serialized)
        self.assertNotIn(str(self.remote), serialized)

    def test_temporary_refs_and_fetch_head_are_untouched(self):
        source = commit(self.repo, "change")
        peer = Path(self.temp.name) / "peer"
        git(Path(self.temp.name), "clone", "--branch", "topic", str(self.remote), str(peer))
        remote_only = commit(peer, "downloaded-only")
        git(peer, "push", "origin", f"{remote_only}:refs/heads/topic")
        self.assertNotEqual(
            subprocess.run(
                ["git", "cat-file", "-e", f"{remote_only}^{{commit}}"],
                cwd=self.repo,
                stderr=subprocess.DEVNULL,
            ).returncode,
            0,
        )
        fetch_head = Path(git(self.repo, "rev-parse", "--git-path", "FETCH_HEAD"))
        if not fetch_head.is_absolute():
            fetch_head = self.repo / fetch_head
        fetch_head.write_text("sentinel\n", encoding="utf-8")

        result = self.plan(raw_request(self.start, source))

        self.assertEqual(result["status"], "needs_reconciliation")
        self.assertEqual(fetch_head.read_text(encoding="utf-8"), "sentinel\n")
        self.assertEqual(git(self.repo, "for-each-ref", "--format=%(refname)", "refs/codex/checkpointing"), "")
        # Exact-fetch objects may persist even though every temporary ref is removed.
        self.assertEqual(git(self.repo, "cat-file", "-t", remote_only), "commit")

    def test_every_git_subprocess_disables_lazy_fetch_and_replacements(self):
        source = commit(self.repo, "change")
        real_run = subprocess.run
        observed = []
        observed_commands = []

        def recording_run(*args, **kwargs):
            command = args[0] if args else kwargs.get("args")
            if command and command[0] == "git" and kwargs.get("cwd") == str(self.repo):
                observed.append(kwargs["env"])
                observed_commands.append(command)
            return real_run(*args, **kwargs)

        adapter.subprocess.run = recording_run
        try:
            result = self.plan(raw_request(self.start, source))
        finally:
            adapter.subprocess.run = real_run

        self.assertEqual(result["status"], "ready")
        self.assertTrue(observed)
        self.assertTrue(
            all(
                env.get("GIT_NO_LAZY_FETCH") == "1"
                and env.get("GIT_NO_REPLACE_OBJECTS") == "1"
                for env in observed
            )
        )
        transport_commands = [
            command
            for command in observed_commands
            if "ls-remote" in command or "fetch" in command
        ]
        self.assertTrue(transport_commands)
        self.assertTrue(
            all(str(self.remote) not in argument for command in transport_commands for argument in command)
        )

    def test_target_change_after_exact_fetch_gates_and_cleans_temp_ref(self):
        source = commit(self.repo, "change")
        original_probe = adapter._probe_ref
        target_probes = 0

        def delete_before_stability_probe(repo, endpoint, ref):
            nonlocal target_probes
            if ref == "refs/heads/topic":
                target_probes += 1
                if target_probes == 2:
                    git(self.repo, "push", "publish", f":{ref}")
            return original_probe(repo, endpoint, ref)

        adapter._probe_ref = delete_before_stability_probe
        try:
            result = self.plan(raw_request(self.start, source))
        finally:
            adapter._probe_ref = original_probe

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "REMOTE_REF_CHANGED_DURING_FETCH")
        self.assertEqual(
            git(self.repo, "for-each-ref", "--format=%(refname)", "refs/codex/checkpointing"), ""
        )
        self.assertEqual(result["destination"]["remote"], "publish")
        self.assertEqual(result["target"], {"present": True, "sha": self.start})
        self.assertNotIn(str(self.remote), json.dumps(result))

    def test_target_creation_between_absence_probes_gates(self):
        source = commit(self.repo, "change")
        request = raw_request(
            self.start,
            source,
            explicit_destination={"remote": "publish", "ref": "refs/heads/new"},
            allow_create=True,
        )
        original_probe = adapter._probe_ref
        calls = 0

        def create_between_probes(repo, endpoint, ref):
            nonlocal calls
            value = original_probe(repo, endpoint, ref)
            if ref == "refs/heads/new":
                calls += 1
                if calls == 1:
                    git(self.repo, "push", "publish", f"{self.start}:{ref}")
            return value

        adapter._probe_ref = create_between_probes
        try:
            result = self.plan(request)
        finally:
            adapter._probe_ref = original_probe

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "REMOTE_REF_APPEARED_DURING_PROBE")

    def test_divergence_requires_exact_target_only_removal_authorization(self):
        remote_only = commit(self.repo, "remote-only")
        git(self.repo, "push", "publish", f"{remote_only}:refs/heads/topic")
        git(self.repo, "reset", "--hard", self.start)
        source = commit(self.repo, "local-only")
        request = raw_request(self.start, source)

        blocked = self.plan(request)
        self.assertEqual(blocked["status"], "needs_reconciliation")
        ready = self.plan(dict(request, removal_authorized_commits=[remote_only]))
        self.assertEqual(ready["status"], "ready")
        self.assertTrue(ready["rewrite_required"])

    def test_explicit_creation_base_requires_adoption(self):
        git(self.repo, "push", "publish", f"{self.start}:refs/heads/main")
        git(self.repo, "push", "publish", ":refs/heads/topic")
        middle = commit(self.repo, "middle")
        source = commit(self.repo, "source")
        request = raw_request(
            middle,
            source,
            explicit_destination={"remote": "publish", "ref": "refs/heads/new"},
            allow_create=True,
            creation_base_ref="refs/heads/main",
        )

        blocked = self.plan(request)
        self.assertEqual(blocked["status"], "blocked")
        ready = self.plan(dict(request, adopted_commits=[middle]))
        self.assertEqual(ready["status"], "ready")

    def test_replace_ref_and_in_progress_operation_block(self):
        source = commit(self.repo, "change")
        git(self.repo, "replace", source, self.start)
        replaced = self.plan(raw_request(self.start, source))
        self.assertEqual(replaced["reasons"][0]["code"], "REPLACE_REFS_PRESENT")
        git(self.repo, "replace", "-d", source)

        merge_head = Path(git(self.repo, "rev-parse", "--git-path", "MERGE_HEAD"))
        if not merge_head.is_absolute():
            merge_head = self.repo / merge_head
        merge_head.write_text(self.start + "\n", encoding="ascii")
        in_progress = self.plan(raw_request(self.start, source))
        self.assertEqual(in_progress["reasons"][0]["code"], "GIT_OPERATION_IN_PROGRESS")

    def test_partial_clone_and_nonempty_grafts_block(self):
        source = commit(self.repo, "change")
        git(self.repo, "config", "remote.publish.promisor", "true")
        partial = self.plan(raw_request(self.start, source))
        self.assertEqual(partial["reasons"][0]["code"], "PARTIAL_OR_PROMISOR_REPOSITORY")
        git(self.repo, "config", "--unset", "remote.publish.promisor")

        grafts = Path(git(self.repo, "rev-parse", "--git-path", "info/grafts"))
        if not grafts.is_absolute():
            grafts = self.repo / grafts
        grafts.parent.mkdir(parents=True, exist_ok=True)
        grafts.write_text(self.start + "\n", encoding="ascii")
        grafted = self.plan(raw_request(self.start, source))
        self.assertEqual(grafted["reasons"][0]["code"], "LEGACY_GRAFTS_PRESENT")

    def test_shallow_repository_blocks(self):
        shallow = Path(self.temp.name) / "shallow"
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/topic")
        git(Path(self.temp.name), "clone", "--depth=1", f"file://{self.remote}", str(shallow))
        result = plan_repository(shallow, raw_request(self.start, self.start))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "SHALLOW_REPOSITORY")

    def test_cli_malformed_request_is_nonzero_json(self):
        request_file = Path(self.temp.name) / "request.json"
        request_file.write_text("{}", encoding="utf-8")
        run = subprocess.run(
            [sys.executable, str(CLI), "--repo", str(self.repo), "--request", str(request_file)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        self.assertNotEqual(run.returncode, 0)
        error = json.loads(run.stdout)
        self.assertEqual(error["schema_version"], 1)
        self.assertEqual(error["error"]["code"], "MALFORMED_REQUEST")

    def test_cli_missing_and_unknown_arguments_are_versioned_json(self):
        for argv in (
            [sys.executable, str(CLI)],
            [sys.executable, str(CLI), "--unknown"],
        ):
            with self.subTest(argv=argv):
                run = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertNotEqual(run.returncode, 0)
                error = json.loads(run.stdout)
                self.assertEqual(error["schema_version"], 1)
                self.assertEqual(error["error"]["code"], "MALFORMED_INVOCATION")

    def test_simple_without_upstream_is_blocked_at_public_seam(self):
        source = commit(self.repo, "change")
        git(self.repo, "config", "branch.topic.pushRemote", "publish")
        result = self.plan(raw_request(self.start, source, explicit_destination=None))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "PUSH_DEFAULT_AMBIGUOUS")

    def test_invalid_configured_push_remote_is_a_repository_gate(self):
        source = commit(self.repo, "change")
        git(self.repo, "config", "branch.topic.pushRemote", "")

        result = self.plan(raw_request(self.start, source, explicit_destination=None))

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "DESTINATION_REMOTE_INVALID")

    def test_remote_push_without_colon_resolves_current_branch(self):
        source = commit(self.repo, "change")
        git(self.repo, "config", "branch.topic.pushRemote", "publish")
        git(self.repo, "config", "branch.topic.remote", "publish")
        git(self.repo, "config", "branch.topic.merge", "refs/heads/topic")
        git(self.repo, "config", "remote.publish.push", "refs/heads/topic")

        result = self.plan(raw_request(self.start, source, explicit_destination=None))

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["destination"]["ref"], "refs/heads/topic")

    def test_every_named_in_progress_operation_blocks_at_public_seam(self):
        source = commit(self.repo, "change")
        markers = {
            "MERGE_HEAD": False,
            "rebase-merge": True,
            "rebase-apply": True,
            "CHERRY_PICK_HEAD": False,
            "REVERT_HEAD": False,
            "BISECT_LOG": False,
            "sequencer": True,
        }
        for marker, is_directory in markers.items():
            path = Path(git(self.repo, "rev-parse", "--git-path", marker))
            if not path.is_absolute():
                path = self.repo / path
            if is_directory:
                path.mkdir(parents=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self.start + "\n", encoding="ascii")
            try:
                result = self.plan(raw_request(self.start, source))
                self.assertEqual(result["status"], "blocked", marker)
                self.assertEqual(result["reasons"][0]["code"], "GIT_OPERATION_IN_PROGRESS")
                self.assertIn(marker, result["reasons"][0]["evidence"]["markers"])
            finally:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)

    def test_temp_ref_collision_is_blocked_without_overwrite_or_cleanup(self):
        source = commit(self.repo, "change")
        token = "1" * 32
        temp_ref = f"refs/codex/checkpointing/{token}"
        git(self.repo, "update-ref", temp_ref, source)
        original_token_hex = adapter.secrets.token_hex
        adapter.secrets.token_hex = lambda _size: token
        try:
            result = self.plan(raw_request(self.start, source))
        finally:
            adapter.secrets.token_hex = original_token_hex

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "TEMP_REF_COLLISION")
        self.assertEqual(git(self.repo, "rev-parse", temp_ref), source)

    def test_temp_ref_cleanup_failure_is_blocked_with_safe_observation_context(self):
        source = commit(self.repo, "change")
        original_run = adapter.GitRepository.run

        def fail_delete(repo, args, check=True, allowed=(), env_overrides=None):
            if args[:2] == ["update-ref", "-d"]:
                return subprocess.CompletedProcess(["git", *args], 1, "", "injected cleanup failure")
            return original_run(
                repo,
                args,
                check=check,
                allowed=allowed,
                env_overrides=env_overrides,
            )

        adapter.GitRepository.run = fail_delete
        try:
            result = self.plan(raw_request(self.start, source))
        finally:
            adapter.GitRepository.run = original_run

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "TEMP_REF_CLEANUP_FAILED")
        self.assertEqual(result["destination"]["remote"], "publish")
        self.assertEqual(result["destination"]["ref"], "refs/heads/topic")
        self.assertTrue(result["destination"]["endpoint_fingerprint"].startswith("sha256:"))
        self.assertTrue(result["destination"]["config_digest"].startswith("sha256:"))
        self.assertEqual(result["target"], {"present": True, "sha": self.start})
        self.assertNotIn(str(self.remote), json.dumps(result))

    def test_existing_target_does_not_probe_unrelated_advertised_heads(self):
        source = commit(self.repo, "change")
        original_run_endpoint = adapter._run_endpoint

        def malformed_heads(repo, endpoint, prefix, suffix=(), **kwargs):
            if prefix == ["ls-remote", "--heads"]:
                return subprocess.CompletedProcess(
                    ["git", *prefix], 0, "malformed-output\n", ""
                )
            return original_run_endpoint(
                repo, endpoint, prefix, suffix, **kwargs
            )

        adapter._run_endpoint = malformed_heads
        try:
            result = self.plan(raw_request(self.start, source))
        finally:
            adapter._run_endpoint = original_run_endpoint

        self.assertEqual(result["status"], "ready")

    def test_absent_target_malformed_advertised_heads_is_a_stable_policy_gate(self):
        source = commit(self.repo, "change")
        original_run_endpoint = adapter._run_endpoint

        def malformed_heads(repo, endpoint, prefix, suffix=(), **kwargs):
            if prefix == ["ls-remote", "--heads"]:
                return subprocess.CompletedProcess(
                    ["git", *prefix], 0, "malformed-output\n", ""
                )
            return original_run_endpoint(
                repo, endpoint, prefix, suffix, **kwargs
            )

        adapter._run_endpoint = malformed_heads
        try:
            result = self.plan(
                raw_request(
                    self.start,
                    source,
                    explicit_destination={
                        "remote": "publish",
                        "ref": "refs/heads/new",
                    },
                    allow_create=True,
                )
            )
        finally:
            adapter._run_endpoint = original_run_endpoint

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"][0]["code"], "REMOTE_REF_PROBE_MALFORMED")
        self.assertEqual(result["destination"]["remote"], "publish")
        self.assertNotIn(str(self.remote), json.dumps(result))

    def test_push_plan_has_a_single_option_boundary(self):
        source = commit(self.repo, "change")
        result = self.plan(raw_request(self.start, source))
        argv = result["push"]["argv"]
        self.assertEqual(argv.count("--"), 1)
        boundary = argv.index("--")
        self.assertTrue(all(item.startswith("-") or item in ("git", "push") for item in argv[:boundary]))
        self.assertEqual(argv[boundary + 1 :], ["publish", f"{source}:refs/heads/topic"])


if __name__ == "__main__":
    unittest.main()
