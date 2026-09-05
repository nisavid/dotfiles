from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from unittest import mock

SKILL_DIR = Path(__file__).resolve().parents[1]
RESOLVER = SKILL_DIR / "scripts" / "resolve_premerge_stack.py"


def load_resolver_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("resolve_premerge_stack", RESOLVER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load resolver module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(
    *args: str,
    cwd: Path,
    check: bool = True,
    environment_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.com",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.com",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
    )
    if environment_overrides:
        environment.update(environment_overrides)
    return subprocess.run(
        args,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=check,
    )


def git(repo: Path, *args: str) -> str:
    return run("git", *args, cwd=repo).stdout.strip()


def commit(repo: Path, name: str, content: str) -> str:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(repo, "add", "--", name)
    git(repo, "commit", "-m", name)
    return git(repo, "rev-parse", "HEAD")


class ResolvePremergeStackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.remote = root / "systalyze.git"
        self.provider = root / "provider"
        self.unrelated_provider = root / "unrelated-provider"
        self.consumer = root / "consumer"
        self.fixture_skill = root / "fixture-skill"
        self.fixture_resolver = (
            self.fixture_skill / "scripts" / "resolve_premerge_stack.py"
        )
        self.manifest = self.fixture_skill / "references" / "premerge-stack.json"
        self.pull_requests = root / "pull-requests.json"
        self.fake_bin = root / "bin"
        self.git_only_bin = root / "git-only-bin"
        self.fake_gh_arguments = root / "gh-arguments.jsonl"
        self.fake_gh_hosts = root / "gh-hosts.txt"
        self.fake_gh_count = root / "gh-query-count"

        self.fake_bin.mkdir()
        self.git_only_bin.mkdir()
        self.fixture_resolver.parent.mkdir(parents=True)
        self.manifest.parent.mkdir(parents=True)
        shutil.copy2(RESOLVER, self.fixture_resolver)
        git_path = shutil.which("git")
        if git_path is None:
            self.fail("git fixture requires git")
        (self.git_only_bin / "git").symlink_to(git_path)
        fake_gh = self.fake_bin / "gh"
        fake_gh.write_text(
            """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

if sys.argv[1:3] == ["auth", "token"]:
    if sys.argv[3:] != ["--hostname", os.environ.get("GH_HOST")]:
        raise SystemExit(98)
    if os.environ.get("FIXTURE_GH_AUTH_GRAFT_PATH"):
        graft_path = Path(os.environ["FIXTURE_GH_AUTH_GRAFT_PATH"])
        graft_path.parent.mkdir(parents=True, exist_ok=True)
        graft_path.write_text(
            os.environ["FIXTURE_GH_AUTH_GRAFT_CONTENT"],
            encoding="utf-8",
        )
    sys.stdout.write("fixture-token\\n")
    raise SystemExit(0)

config_dir = os.environ.get("GH_CONFIG_DIR")
if config_dir and (Path(config_dir) / "reject-pr-transport").exists():
    raise SystemExit(97)
if os.environ.get("GH_TOKEN") != "fixture-token":
    raise SystemExit(96)
if any(
    variable in os.environ
    for variable in ("GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
):
    raise SystemExit(95)

count_path = Path(os.environ["FIXTURE_GH_COUNT"])
count = int(count_path.read_text(encoding="utf-8")) if count_path.exists() else 0
with Path(os.environ["FIXTURE_GH_ARGUMENTS"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
with Path(os.environ["FIXTURE_GH_HOSTS"]).open("a", encoding="utf-8") as stream:
    stream.write(os.environ.get("GH_HOST", "") + "\\n")
if count == 0 and os.environ.get("FIXTURE_GH_ALIAS_REF"):
    subprocess.run(
        [
            "git",
            "--git-dir",
            os.environ["FIXTURE_GH_REMOTE"],
            "update-ref",
            os.environ["FIXTURE_GH_ALIAS_REF"],
            os.environ["FIXTURE_GH_ALIAS_OID"],
        ],
        check=True,
        capture_output=True,
        text=True,
    )
if count == 0 and os.environ.get("FIXTURE_GH_REPLACEMENT_REMOTE_URL"):
    subprocess.run(
        [
            "git",
            "-C",
            os.environ["FIXTURE_GH_REPO"],
            "remote",
            "set-url",
            "origin",
            os.environ["FIXTURE_GH_REPLACEMENT_REMOTE_URL"],
        ],
        check=True,
        capture_output=True,
        text=True,
    )
if count == 0 and os.environ.get("FIXTURE_GH_INSTEAD_OF_SOURCE"):
    subprocess.run(
        [
            "git",
            "-C",
            os.environ["FIXTURE_GH_REPO"],
            "config",
            "--add",
            f"url.{os.environ['FIXTURE_GH_INSTEAD_OF_TARGET']}.insteadOf",
            os.environ["FIXTURE_GH_INSTEAD_OF_SOURCE"],
        ],
        check=True,
        capture_output=True,
        text=True,
    )
if count == 0 and os.environ.get("FIXTURE_GH_GRAFT_PATH"):
    graft_path = Path(os.environ["FIXTURE_GH_GRAFT_PATH"])
    graft_path.parent.mkdir(parents=True, exist_ok=True)
    graft_path.write_text(
        os.environ["FIXTURE_GH_GRAFT_CONTENT"],
        encoding="utf-8",
    )
source = os.environ.get("FIXTURE_GH_FINAL") if count else None
source = source or os.environ["FIXTURE_GH_PRIMARY"]
count_path.write_text(str(count + 1), encoding="utf-8")
sys.stdout.write(Path(source).read_text(encoding="utf-8"))
""",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)

        run("git", "init", "--bare", str(self.remote), cwd=root)
        run("git", "init", "-b", "main", str(self.provider), cwd=root)
        self.base = commit(self.provider, "base.txt", "base\n")
        self.grounding = commit(self.provider, "grounding.txt", "grounding\n")

        git(self.provider, "switch", "-c", "fixture-dev-tooling", self.base)
        self.local_dev = commit(self.provider, "local-dev.txt", "local dev\n")
        git(self.provider, "switch", "main")

        git(self.provider, "remote", "add", "origin", str(self.remote))
        git(
            self.provider,
            "push",
            "origin",
            f"{self.base}:refs/heads/main",
            f"{self.grounding}:refs/heads/ivan/product-grounding",
            f"{self.local_dev}:refs/heads/ivan/docker-only-local-dev",
            f"{self.grounding}:refs/heads/ivan/stack-tips/grounding-docs",
            f"{self.local_dev}:refs/heads/ivan/stack-tips/dev-tooling",
        )

        run("git", "init", "-b", "unrelated", str(self.unrelated_provider), cwd=root)
        self.unrelated = commit(self.unrelated_provider, "unrelated.txt", "unrelated\n")
        git(self.unrelated_provider, "remote", "add", "origin", str(self.remote))
        git(
            self.unrelated_provider,
            "push",
            "origin",
            f"{self.unrelated}:refs/heads/ivan/unrelated",
        )

        run("git", "init", "-b", "task", str(self.consumer), cwd=root)
        git(self.consumer, "remote", "add", "origin", str(self.remote))
        git(
            self.consumer,
            "fetch",
            "--no-tags",
            "origin",
            "refs/heads/main:refs/remotes/origin/main",
        )
        git(self.consumer, "switch", "--detach", "refs/remotes/origin/main")

        self.write_manifest([str(self.remote)])
        self.write_pull_requests(self.grounding, self.local_dev)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def manifest_document(remote_urls: list[str]) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "repository": "github.com/systalyze/systalyze",
            "remoteUrls": remote_urls,
            "surfaces": [
                {
                    "name": "grounding-docs",
                    "role": "product-base",
                    "ref": "refs/heads/ivan/stack-tips/grounding-docs",
                },
                {
                    "name": "dev-tooling",
                    "role": "qa-overlay",
                    "ref": "refs/heads/ivan/stack-tips/dev-tooling",
                },
            ],
            "relationships": [
                {
                    "left": "grounding-docs",
                    "right": "dev-tooling",
                    "require": "common-ancestor",
                }
            ],
        }

    def write_manifest_document(self, document: object) -> None:
        self.manifest.write_text(json.dumps(document) + "\n", encoding="utf-8")

    def write_manifest(self, remote_urls: list[str]) -> None:
        self.write_manifest_document(self.manifest_document(remote_urls))

    def write_pull_requests(self, grounding: str, local_dev: str) -> None:
        self.pull_requests.write_text(
            json.dumps(
                [
                    {
                        "number": 101,
                        "headRefName": "ivan/product-grounding",
                        "headRefOid": grounding,
                        "baseRefName": "main",
                        "baseRefOid": self.base,
                        "isCrossRepository": False,
                        "isDraft": False,
                        "url": "https://example.invalid/pull/101",
                    },
                    {
                        "number": 202,
                        "headRefName": "ivan/docker-only-local-dev",
                        "headRefOid": local_dev,
                        "baseRefName": "ivan/product-grounding",
                        "baseRefOid": grounding,
                        "isCrossRepository": False,
                        "isDraft": True,
                        "url": "https://example.invalid/pull/202",
                    },
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def configure_fake_ssh_transport(self) -> Path:
        ssh_calls = self.consumer.parent / "ssh-calls.jsonl"
        fake_ssh = self.fake_bin / "ssh"
        fake_ssh.write_text(
            """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

with Path(os.environ["FIXTURE_SSH_CALLS"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
os.execlp(
    "git-upload-pack",
    "git-upload-pack",
    os.environ["FIXTURE_SSH_REMOTE"],
)
""",
            encoding="utf-8",
        )
        fake_ssh.chmod(0o755)
        return ssh_calls

    def configure_ssh_remote(self) -> Path:
        ssh_calls = self.configure_fake_ssh_transport()
        fake_ssh = self.fake_bin / "ssh"
        resolver_source = self.fixture_resolver.read_text(encoding="utf-8")
        trusted_source = 'TRUSTED_OPENSSH_EXECUTABLE = Path("/usr/bin/ssh")'
        self.assertIn(trusted_source, resolver_source)
        self.fixture_resolver.write_text(
            resolver_source.replace(
                trusted_source,
                f"TRUSTED_OPENSSH_EXECUTABLE = Path({str(fake_ssh)!r})",
                1,
            ),
            encoding="utf-8",
        )
        remote_url = "ssh://fixture/systalyze/systalyze.git"
        git(self.consumer, "remote", "set-url", "origin", remote_url)
        document = self.manifest_document([remote_url])
        document["repository"] = "fixture/systalyze/systalyze"
        self.write_manifest_document(document)
        return ssh_calls

    def resolve(
        self,
        *,
        repo: Path | None = None,
        final_pull_requests: Path | None = None,
        alias_move: tuple[str, str] | None = None,
        replacement_remote_url: str | None = None,
        instead_of_rewrite: tuple[str, str] | None = None,
        auth_graft: tuple[Path, str] | None = None,
        late_graft: tuple[Path, str] | None = None,
        missing_gh: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        self.fake_gh_count.unlink(missing_ok=True)
        self.fake_gh_arguments.unlink(missing_ok=True)
        self.fake_gh_hosts.unlink(missing_ok=True)
        environment = {
            "PATH": (
                str(self.git_only_bin)
                if missing_gh
                else str(self.fake_bin) + os.pathsep + os.environ["PATH"]
            ),
            "FIXTURE_GH_COUNT": str(self.fake_gh_count),
            "FIXTURE_GH_ARGUMENTS": str(self.fake_gh_arguments),
            "FIXTURE_GH_HOSTS": str(self.fake_gh_hosts),
            "FIXTURE_GH_PRIMARY": str(self.pull_requests),
            "GH_HOST": "example.invalid",
        }
        if final_pull_requests is not None:
            environment["FIXTURE_GH_FINAL"] = str(final_pull_requests)
        if alias_move is not None:
            alias_ref, alias_oid = alias_move
            environment.update(
                {
                    "FIXTURE_GH_REMOTE": str(self.remote),
                    "FIXTURE_GH_ALIAS_REF": alias_ref,
                    "FIXTURE_GH_ALIAS_OID": alias_oid,
                }
            )
        if replacement_remote_url is not None:
            environment.update(
                {
                    "FIXTURE_GH_REPO": str(self.consumer),
                    "FIXTURE_GH_REPLACEMENT_REMOTE_URL": replacement_remote_url,
                }
            )
        if instead_of_rewrite is not None:
            source, target = instead_of_rewrite
            environment.update(
                {
                    "FIXTURE_GH_REPO": str(self.consumer),
                    "FIXTURE_GH_INSTEAD_OF_SOURCE": source,
                    "FIXTURE_GH_INSTEAD_OF_TARGET": target,
                }
            )
        if auth_graft is not None:
            path, contents = auth_graft
            environment.update(
                {
                    "FIXTURE_GH_AUTH_GRAFT_PATH": str(path),
                    "FIXTURE_GH_AUTH_GRAFT_CONTENT": contents,
                }
            )
        if late_graft is not None:
            path, contents = late_graft
            environment.update(
                {
                    "FIXTURE_GH_GRAFT_PATH": str(path),
                    "FIXTURE_GH_GRAFT_CONTENT": contents,
                }
            )
        return run(
            sys.executable,
            str(self.fixture_resolver),
            "--repo",
            str(repo or self.consumer),
            "--remote",
            "origin",
            cwd=repo or self.consumer,
            check=False,
            environment_overrides=environment,
        )

    @staticmethod
    def error_document(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        return json.loads(result.stderr)

    @classmethod
    def error_code(cls, result: subprocess.CompletedProcess[str]) -> str:
        return cls.error_document(result)["error"]["code"]

    def test_resolves_immutable_aliases_without_changing_refs_or_worktree(self) -> None:
        fetch_head = self.consumer / ".git" / "FETCH_HEAD"
        fetch_head_contents = b"preserve this FETCH_HEAD exactly\n"
        fetch_head.write_bytes(fetch_head_contents)
        refs_before = git(self.consumer, "show-ref")
        status_before = git(self.consumer, "status", "--short")
        head_before = git(self.consumer, "rev-parse", "HEAD")

        result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document["repository"], "github.com/systalyze/systalyze")
        self.assertEqual(document["surfaces"]["grounding-docs"]["oid"], self.grounding)
        self.assertEqual(
            document["surfaces"]["grounding-docs"]["pullRequest"]["number"], 101
        )
        self.assertEqual(document["surfaces"]["dev-tooling"]["oid"], self.local_dev)
        self.assertEqual(
            document["surfaces"]["dev-tooling"]["pullRequest"]["number"], 202
        )
        self.assertEqual(document["relationships"][0]["mergeBaseOid"], self.base)
        self.assertFalse(document["relationships"][0]["leftIsAncestorOfRight"])
        self.assertFalse(document["relationships"][0]["rightIsAncestorOfLeft"])
        gh_arguments = [
            json.loads(line)
            for line in self.fake_gh_arguments.read_text(encoding="utf-8").splitlines()
        ]
        expected_arguments = [
            "pr",
            "list",
            "--repo",
            "github.com/systalyze/systalyze",
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "number,headRefName,headRefOid,baseRefName,baseRefOid,isCrossRepository,isDraft,url",
        ]
        self.assertEqual(gh_arguments, [expected_arguments, expected_arguments])
        self.assertEqual(
            self.fake_gh_hosts.read_text(encoding="utf-8").splitlines(),
            ["github.com", "github.com"],
        )
        self.assertEqual(git(self.consumer, "show-ref"), refs_before)
        self.assertEqual(fetch_head.read_bytes(), fetch_head_contents)
        self.assertEqual(git(self.consumer, "status", "--short"), status_before)
        self.assertEqual(git(self.consumer, "rev-parse", "HEAD"), head_before)

    def test_non_ssh_remote_ignores_unrecognized_ambient_ssh_wrapper(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"GIT_SSH_COMMAND": "custom-ssh-wrapper --mode fixture"},
            clear=False,
        ):
            result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_non_ssh_remote_ignores_unrecognized_configured_ssh_wrapper(self) -> None:
        git(
            self.consumer,
            "config",
            "core.sshCommand",
            "custom-ssh-wrapper --mode fixture",
        )
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GIT_SSH_COMMAND", None)
            result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_remote_name_change_cannot_redirect_verified_operations(self) -> None:
        ssh_calls = self.configure_fake_ssh_transport()
        with mock.patch.dict(
            os.environ,
            {
                "FIXTURE_SSH_CALLS": str(ssh_calls),
                "FIXTURE_SSH_REMOTE": str(self.remote),
                "GIT_SSH_COMMAND": "ssh",
            },
            clear=False,
        ):
            result = self.resolve(
                replacement_remote_url="ssh://fixture/systalyze/systalyze.git"
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(ssh_calls.exists())

    def test_late_same_transport_rewrite_cannot_redirect_verified_operations(
        self,
    ) -> None:
        original_url = self.remote.as_uri()
        mirror = self.remote.with_name("mirror.git")
        run("git", "init", "--bare", str(mirror), cwd=self.consumer.parent)
        mirror_url = mirror.as_uri()
        git(self.consumer, "remote", "set-url", "origin", original_url)
        self.write_manifest([original_url])

        result = self.resolve(
            instead_of_rewrite=(original_url, mirror_url),
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ambient_git_template_cannot_redirect_private_transport(self) -> None:
        original_url = self.remote.as_uri()
        mirror = self.remote.with_name("template-mirror.git")
        run("git", "init", "--bare", str(mirror), cwd=self.consumer.parent)
        mirror_url = mirror.as_uri()
        git(
            self.provider,
            "push",
            mirror_url,
            f"{self.local_dev}:refs/heads/ivan/stack-tips/grounding-docs",
            f"{self.grounding}:refs/heads/ivan/stack-tips/dev-tooling",
        )
        git(self.consumer, "remote", "set-url", "origin", original_url)
        self.write_manifest([original_url])
        template = self.consumer.parent / "malicious-template"
        template.mkdir()
        (template / "config").write_text(
            "[core]\n"
            "\trepositoryformatversion = 0\n"
            "\tbare = true\n"
            f'[url "{mirror_url}"]\n'
            f"\tinsteadOf = {original_url}\n",
            encoding="utf-8",
        )

        with mock.patch.dict(
            os.environ,
            {"GIT_TEMPLATE_DIR": str(template)},
            clear=False,
        ):
            result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document["surfaces"]["grounding-docs"]["oid"], self.grounding)
        self.assertEqual(document["surfaces"]["dev-tooling"]["oid"], self.local_dev)

    def test_ambient_default_hash_cannot_change_private_transport_format(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"GIT_DEFAULT_HASH": "sha256"},
            clear=False,
        ):
            result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_nonstandard_remote_fetch_mapping(self) -> None:
        git(self.consumer, "config", "--unset-all", "remote.origin.fetch")
        git(
            self.consumer,
            "config",
            "--add",
            "remote.origin.fetch",
            "+refs/heads/*:refs/cache/origin/*",
        )

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            self.error_code(result),
            "REMOTE_FETCH_REFSPEC_UNSUPPORTED",
        )

    def test_rejects_repository_grafts_before_network_access(self) -> None:
        graft_path = Path(git(self.consumer, "rev-parse", "--git-path", "info/grafts"))
        if not graft_path.is_absolute():
            graft_path = self.consumer / graft_path
        graft_path.parent.mkdir(parents=True, exist_ok=True)
        graft_path.write_text(
            f"{self.grounding} {self.unrelated}\n",
            encoding="utf-8",
        )

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "REPOSITORY_GRAFTS_UNSUPPORTED")
        self.assertFalse(self.fake_gh_arguments.exists())

    def test_rejects_shallow_repository_with_specific_error(self) -> None:
        shallow_path = Path(git(self.consumer, "rev-parse", "--git-path", "shallow"))
        if not shallow_path.is_absolute():
            shallow_path = self.consumer / shallow_path
        shallow_path.write_text(f"{self.base}\n", encoding="utf-8")

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "SHALLOW_REPOSITORY_UNSUPPORTED")
        self.assertFalse(self.fake_gh_arguments.exists())

    def test_rejects_promisor_repository_before_object_lookup(self) -> None:
        git(self.consumer, "config", "remote.origin.promisor", "true")

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "PROMISOR_REPOSITORY_UNSUPPORTED")
        self.assertFalse(self.fake_gh_arguments.exists())

    def test_non_ssh_network_operation_blocks_late_ssh_rewrite(self) -> None:
        resolver = load_resolver_module()
        ssh_calls = self.configure_fake_ssh_transport()
        git(
            self.consumer,
            "config",
            "url.ssh://fixture/.insteadOf",
            str(self.remote),
        )
        with (
            mock.patch.dict(
                os.environ,
                {
                    "FIXTURE_SSH_CALLS": str(ssh_calls),
                    "FIXTURE_SSH_REMOTE": str(self.remote),
                    "GIT_SSH_COMMAND": "ssh",
                    "PATH": str(self.fake_bin) + os.pathsep + os.environ["PATH"],
                },
                clear=False,
            ),
            self.assertRaises(resolver.ContractError),
        ):
            resolver.run(
                ["git", "ls-remote", str(self.remote)],
                cwd=self.consumer,
                failure_code="NON_SSH_TRANSPORT_CHANGED",
                uses_ssh_transport=False,
            )

        self.assertFalse(ssh_calls.exists())

    def test_https_tls_verification_override_fails_closed(self) -> None:
        remote_url = "https://github.com/systalyze/systalyze"
        git(self.consumer, "remote", "set-url", "origin", remote_url)
        git(self.consumer, "config", "http.proxy", "http://127.0.0.1:9")
        git(self.consumer, "config", "http.sslVerify", "false")
        self.write_manifest([remote_url])

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "TLS_VERIFICATION_DISABLED")
        self.assertFalse(self.fake_gh_arguments.exists())

    def test_https_tls_environment_override_fails_closed(self) -> None:
        remote_url = "https://github.com/systalyze/systalyze"
        git(self.consumer, "remote", "set-url", "origin", remote_url)
        git(self.consumer, "config", "http.proxy", "http://127.0.0.1:9")
        self.write_manifest([remote_url])

        with mock.patch.dict(
            os.environ,
            {"GIT_SSL_NO_VERIFY": "1"},
            clear=False,
        ):
            result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "TLS_VERIFICATION_DISABLED")
        self.assertFalse(self.fake_gh_arguments.exists())

    def test_unrelated_https_tls_override_is_ignored(self) -> None:
        resolver = load_resolver_module()

        resolver.verify_https_transport_security(
            "https://github.com/systalyze/systalyze",
            (("http.https://unrelated.example.invalid/.sslVerify", "false"),),
        )

    def test_github_queries_ignore_unix_socket_configuration(self) -> None:
        config_dir = self.consumer.parent / "malicious-gh-config"
        config_dir.mkdir()
        (config_dir / "reject-pr-transport").touch()
        ambient_environment = dict.fromkeys(
            (
                "GH_TOKEN",
                "GITHUB_TOKEN",
                "GH_ENTERPRISE_TOKEN",
                "GITHUB_ENTERPRISE_TOKEN",
            ),
            "ambient-authentication",
        )
        ambient_environment["GH_CONFIG_DIR"] = str(config_dir)

        with mock.patch.dict(
            os.environ,
            ambient_environment,
            clear=False,
        ):
            result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_resolver_hardens_every_ssh_remote_operation(self) -> None:
        ssh_calls = self.configure_ssh_remote()
        with mock.patch.dict(
            os.environ,
            {
                "FIXTURE_SSH_CALLS": str(ssh_calls),
                "FIXTURE_SSH_REMOTE": str(self.remote),
                "GIT_SSH_COMMAND": "ssh",
            },
            clear=False,
        ):
            result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = [
            json.loads(line)
            for line in ssh_calls.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(invocations), 4)
        for arguments in invocations:
            with self.subTest(arguments=arguments):
                option_index = arguments.index("-o")
                self.assertEqual(arguments[option_index + 1], "BatchMode=yes")
                self.assertIn("StrictHostKeyChecking=yes", arguments)
                self.assertIn("ProxyCommand=none", arguments)
                self.assertIn("ProxyJump=none", arguments)
                self.assertIn("HostName=fixture", arguments)
                self.assertIn("HostKeyAlias=fixture", arguments)
                self.assertIn("Port=22", arguments)
                self.assertTrue(arguments[-1].startswith("git-upload-pack "))

    def test_ssh_remote_rejects_shell_execution_in_arguments(self) -> None:
        ssh_calls = self.configure_ssh_remote()
        marker = self.consumer.parent / "shell-expansion-marker"
        git(
            self.consumer,
            "config",
            "core.sshCommand",
            f"ssh `touch {shlex.quote(str(marker))}`",
        )
        with mock.patch.dict(
            os.environ,
            {
                "FIXTURE_SSH_CALLS": str(ssh_calls),
                "FIXTURE_SSH_REMOTE": str(self.remote),
            },
            clear=False,
        ):
            os.environ.pop("GIT_SSH_COMMAND", None)
            result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "ALIAS_QUERY_FAILED")
        self.assertEqual(
            self.error_document(result)["error"]["evidence"],
            {"command": "git", "sshCommandUnsupported": True},
        )
        self.assertFalse(marker.exists())
        self.assertFalse(ssh_calls.exists())

    def test_resolver_pins_git_ssh_variant(self) -> None:
        ssh_calls = self.configure_ssh_remote()
        git(
            self.consumer,
            "remote",
            "set-url",
            "origin",
            "ssh://fixture:22/systalyze/systalyze.git",
        )
        with mock.patch.dict(
            os.environ,
            {
                "FIXTURE_SSH_CALLS": str(ssh_calls),
                "FIXTURE_SSH_REMOTE": str(self.remote),
                "GIT_SSH_COMMAND": "ssh",
                "GIT_SSH_VARIANT": "simple",
            },
            clear=False,
        ):
            result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(ssh_calls.exists())

    def test_ssh_remote_rejects_unrecognized_wrapper_before_transport(self) -> None:
        ssh_calls = self.configure_ssh_remote()
        for ssh_command in (
            "custom-ssh-wrapper --mode fixture",
            "'x=y' ssh",
        ):
            with (
                self.subTest(ssh_command=ssh_command),
                mock.patch.dict(
                    os.environ,
                    {
                        "FIXTURE_SSH_CALLS": str(ssh_calls),
                        "FIXTURE_SSH_REMOTE": str(self.remote),
                        "GIT_SSH_COMMAND": ssh_command,
                    },
                    clear=False,
                ),
            ):
                result = self.resolve()

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.error_code(result), "ALIAS_QUERY_FAILED")
                self.assertEqual(
                    self.error_document(result)["error"]["evidence"],
                    {"command": "git", "sshCommandUnsupported": True},
                )
                self.assertFalse(ssh_calls.exists())

    def test_missing_alias_fails_closed(self) -> None:
        run(
            "git",
            "--git-dir",
            str(self.remote),
            "update-ref",
            "-d",
            "refs/heads/ivan/stack-tips/dev-tooling",
            cwd=self.consumer,
        )

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "ALIAS_MISSING")
        evidence = self.error_document(result)["error"]["evidence"]
        self.assertEqual(
            evidence["observedRefs"]["refs/heads/ivan/stack-tips/grounding-docs"],
            [self.grounding],
        )
        self.assertEqual(
            evidence["observedRefs"]["refs/heads/ivan/stack-tips/dev-tooling"],
            [],
        )

    def test_immutable_fetch_does_not_recurse_into_nested_repository(self) -> None:
        root = Path(self.temporary_directory.name)
        nested_remote = root / "nested.git"
        nested_provider = root / "nested-provider"
        outer_remote = root / "outer.git"
        outer_provider = root / "outer-provider"
        outer_consumer = root / "outer-consumer"

        run("git", "init", "--bare", str(nested_remote), cwd=root)
        run("git", "init", "-b", "main", str(nested_provider), cwd=root)
        nested_base = commit(nested_provider, "nested.txt", "base\n")
        git(nested_provider, "remote", "add", "origin", str(nested_remote))
        git(nested_provider, "push", "origin", "main")

        run("git", "init", "--bare", str(outer_remote), cwd=root)
        run("git", "init", "-b", "main", str(outer_provider), cwd=root)
        run(
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-b",
            "main",
            str(nested_remote),
            "nested",
            cwd=outer_provider,
        )
        outer_base = commit(outer_provider, "outer.txt", "base\n")
        git(outer_provider, "remote", "add", "origin", str(outer_remote))
        git(outer_provider, "push", "origin", f"{outer_base}:refs/heads/main")

        run("git", "init", "-b", "task", str(outer_consumer), cwd=root)
        git(outer_consumer, "remote", "add", "origin", str(outer_remote))
        git(
            outer_consumer,
            "fetch",
            "--no-tags",
            "origin",
            "refs/heads/main:refs/remotes/origin/main",
        )
        git(outer_consumer, "switch", "--detach", "refs/remotes/origin/main")
        run(
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "--init",
            cwd=outer_consumer,
        )
        nested_checkout = outer_consumer / "nested"
        self.assertEqual(
            git(nested_checkout, "rev-parse", "refs/remotes/origin/main"),
            nested_base,
        )

        nested_next = commit(nested_provider, "nested.txt", "next\n")
        git(nested_provider, "push", "origin", "main")
        git(outer_provider / "nested", "fetch", "origin", "main")
        git(outer_provider / "nested", "checkout", nested_next)
        (outer_provider / "grounding.txt").write_text("grounding\n", encoding="utf-8")
        git(outer_provider, "add", "--", "nested", "grounding.txt")
        git(outer_provider, "commit", "-m", "outer-grounding")
        outer_grounding = git(outer_provider, "rev-parse", "HEAD")

        git(outer_provider, "switch", "-c", "fixture-dev", outer_base)
        outer_dev = commit(outer_provider, "dev.txt", "dev\n")
        git(
            outer_provider,
            "push",
            "origin",
            f"{outer_grounding}:refs/heads/ivan/stack-tips/grounding-docs",
            f"{outer_dev}:refs/heads/ivan/stack-tips/dev-tooling",
        )

        self.write_manifest([str(outer_remote)])
        self.write_pull_requests(outer_grounding, outer_dev)
        git(outer_consumer, "config", "fetch.recurseSubmodules", "true")
        nested_refs_before = git(nested_checkout, "show-ref")
        nested_head_before = git(nested_checkout, "rev-parse", "HEAD")
        nested_status_before = git(nested_checkout, "status", "--short")

        result = self.resolve(repo=outer_consumer)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(nested_checkout, "show-ref"), nested_refs_before)
        self.assertEqual(git(nested_checkout, "rev-parse", "HEAD"), nested_head_before)
        self.assertEqual(
            git(nested_checkout, "status", "--short"), nested_status_before
        )
        self.assertEqual(
            git(nested_checkout, "rev-parse", "refs/remotes/origin/main"),
            nested_base,
        )

    def test_alias_without_one_live_pull_request_fails_closed(self) -> None:
        self.write_pull_requests(self.grounding, self.unrelated)

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "PR_IDENTITY_MISMATCH")

    def test_alias_branch_pull_request_cannot_satisfy_provider_identity(self) -> None:
        document = json.loads(self.pull_requests.read_text(encoding="utf-8"))
        document[0]["headRefName"] = "ivan/stack-tips/grounding-docs"
        self.pull_requests.write_text(json.dumps(document) + "\n", encoding="utf-8")

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "PR_IDENTITY_MISMATCH")
        self.assertEqual(
            self.error_document(result)["error"]["evidence"],
            {"aliasHeads": ["ivan/stack-tips/grounding-docs"]},
        )

    def test_fork_pull_request_with_alias_branch_name_is_not_rejected(self) -> None:
        document = json.loads(self.pull_requests.read_text(encoding="utf-8"))
        document.append(
            {
                "number": 303,
                "headRefName": "ivan/stack-tips/grounding-docs",
                "headRefOid": self.unrelated,
                "baseRefName": "main",
                "baseRefOid": self.base,
                "isCrossRepository": True,
                "isDraft": True,
                "url": "https://example.invalid/pull/303",
            }
        )
        self.pull_requests.write_text(json.dumps(document) + "\n", encoding="utf-8")

        result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fork_pull_request_cannot_satisfy_provider_identity(self) -> None:
        document = json.loads(self.pull_requests.read_text(encoding="utf-8"))
        document[0]["isCrossRepository"] = True
        self.pull_requests.write_text(json.dumps(document) + "\n", encoding="utf-8")

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "PR_IDENTITY_MISMATCH")

    def test_same_oid_fork_does_not_make_provider_identity_ambiguous(self) -> None:
        document = json.loads(self.pull_requests.read_text(encoding="utf-8"))
        fork_pull_request = dict(document[0])
        fork_pull_request.update(
            {
                "number": 303,
                "headRefName": "fork-product-grounding",
                "isCrossRepository": True,
                "url": "https://example.invalid/pull/303",
            }
        )
        document.append(fork_pull_request)
        self.pull_requests.write_text(json.dumps(document) + "\n", encoding="utf-8")

        result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_aliases_without_common_history_fail_closed(self) -> None:
        run(
            "git",
            "--git-dir",
            str(self.remote),
            "update-ref",
            "refs/heads/ivan/stack-tips/dev-tooling",
            self.unrelated,
            cwd=self.consumer,
        )
        self.write_pull_requests(self.grounding, self.unrelated)

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "RELATIONSHIP_MISMATCH")

    def test_late_repository_graft_cannot_fabricate_common_history(self) -> None:
        run(
            "git",
            "--git-dir",
            str(self.remote),
            "update-ref",
            "refs/heads/ivan/stack-tips/dev-tooling",
            self.unrelated,
            cwd=self.consumer,
        )
        self.write_pull_requests(self.grounding, self.unrelated)
        graft_path = Path(git(self.consumer, "rev-parse", "--git-path", "info/grafts"))
        if not graft_path.is_absolute():
            graft_path = self.consumer / graft_path

        result = self.resolve(
            late_graft=(graft_path, f"{self.unrelated} {self.grounding}\n")
        )

        self.assertTrue(graft_path.exists())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "RELATIONSHIP_MISMATCH")

    def test_local_replace_refs_cannot_fabricate_common_history(self) -> None:
        run(
            "git",
            "--git-dir",
            str(self.remote),
            "update-ref",
            "refs/heads/ivan/stack-tips/dev-tooling",
            self.unrelated,
            cwd=self.consumer,
        )
        self.write_pull_requests(self.grounding, self.unrelated)
        git(
            self.consumer,
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            "origin",
            self.local_dev,
            self.unrelated,
        )
        git(self.consumer, "replace", self.unrelated, self.local_dev)

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "RELATIONSHIP_MISMATCH")

    def test_non_fast_forward_change_from_cached_alias_fails_closed(self) -> None:
        git(
            self.consumer,
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            "origin",
            self.unrelated,
        )
        git(
            self.consumer,
            "update-ref",
            "refs/remotes/origin/ivan/stack-tips/grounding-docs",
            self.unrelated,
        )

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "UNEXPECTED_ALIAS_REWRITE")

    def test_fetch_negotiation_does_not_advertise_unpublished_head(self) -> None:
        cached_only = commit(self.consumer, "cached-only.txt", "cached only\n")
        private_head = commit(self.consumer, "private.txt", "private\n")
        for surface in ("grounding-docs", "dev-tooling"):
            git(
                self.consumer,
                "update-ref",
                f"refs/remotes/origin/ivan/stack-tips/{surface}",
                cached_only,
            )
        trace = self.consumer.parent / "git-packets.log"

        with mock.patch.dict(
            os.environ,
            {"GIT_TRACE_PACKET": str(trace)},
            clear=False,
        ):
            result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "UNEXPECTED_ALIAS_REWRITE")
        trace_contents = trace.read_text(encoding="utf-8")
        self.assertNotIn(private_head, trace_contents)
        self.assertNotIn(cached_only, trace_contents)
        self.assertIn(f"have {self.base}", trace_contents)

    def test_late_repository_graft_cannot_hide_cached_alias_rewrite(self) -> None:
        git(
            self.consumer,
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            "origin",
            self.unrelated,
        )
        git(
            self.consumer,
            "update-ref",
            "refs/remotes/origin/ivan/stack-tips/grounding-docs",
            self.unrelated,
        )
        graft_path = Path(git(self.consumer, "rev-parse", "--git-path", "info/grafts"))
        if not graft_path.is_absolute():
            graft_path = self.consumer / graft_path

        result = self.resolve(
            auth_graft=(graft_path, f"{self.grounding} {self.unrelated}\n")
        )

        self.assertTrue(graft_path.exists())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "UNEXPECTED_ALIAS_REWRITE")

    def test_missing_cached_alias_object_fails_closed(self) -> None:
        cached_ref = (
            self.consumer
            / ".git"
            / "refs/remotes/origin/ivan/stack-tips/grounding-docs"
        )
        cached_ref.parent.mkdir(parents=True, exist_ok=True)
        cached_ref.write_text("f" * 40 + "\n", encoding="ascii")

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            self.error_code(result),
            "CACHED_ALIAS_OBJECT_UNAVAILABLE",
        )
        self.assertFalse(self.fake_gh_arguments.exists())

    def test_unverified_remote_fails_closed(self) -> None:
        self.write_manifest(["https://example.invalid/not-systalyze"])

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "REMOTE_IDENTITY_MISMATCH")

    def test_invalid_manifest_shapes_fail_closed(self) -> None:
        with self.subTest("unparsable JSON"):
            self.manifest.write_text("{", encoding="utf-8")
            result = self.resolve()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.error_code(result), "MANIFEST_INVALID")

        remote_urls = [str(self.remote)]
        unknown_key = self.manifest_document(remote_urls)
        unknown_key["unknown"] = True

        duplicate_role = self.manifest_document(remote_urls)
        cast(list[dict[str, object]], duplicate_role["surfaces"])[1]["role"] = (
            "product-base"
        )

        swapped_roles = self.manifest_document(remote_urls)
        cast(list[dict[str, object]], swapped_roles["surfaces"])[0]["role"] = (
            "qa-overlay"
        )
        cast(list[dict[str, object]], swapped_roles["surfaces"])[1]["role"] = (
            "product-base"
        )

        tag_ref = self.manifest_document(remote_urls)
        cast(list[dict[str, object]], tag_ref["surfaces"])[1]["ref"] = (
            "refs/tags/dev-tooling"
        )

        unsupported_relationship = self.manifest_document(remote_urls)
        cast(list[dict[str, object]], unsupported_relationship["relationships"])[0][
            "require"
        ] = "left-contains-right"

        nonstring_relationship_name = self.manifest_document(remote_urls)
        cast(list[dict[str, object]], nonstring_relationship_name["relationships"])[0][
            "left"
        ] = []

        hostless_repository = self.manifest_document(remote_urls)
        hostless_repository["repository"] = "systalyze/systalyze"

        malformed_remote_url = self.manifest_document(
            [str(self.remote), "not a remote URL"]
        )

        malformed_remote_authority = self.manifest_document(
            [str(self.remote), "https://[::1"]
        )

        malformed_scp_authority = self.manifest_document(
            [str(self.remote), "git@[foo:owner/repo"]
        )

        zero_ssh_port = self.manifest_document(
            [str(self.remote), "ssh://github.com:0/systalyze/systalyze.git"]
        )

        nul_local_path = self.manifest_document(
            [str(self.remote), "file:///tmp/\N{NULL}"]
        )

        for name, document in (
            ("unknown key", unknown_key),
            ("duplicate role", duplicate_role),
            ("swapped roles", swapped_roles),
            ("tag ref", tag_ref),
            ("unsupported relationship", unsupported_relationship),
            ("non-string relationship name", nonstring_relationship_name),
            ("hostless repository", hostless_repository),
            ("malformed remote URL", malformed_remote_url),
            ("malformed remote authority", malformed_remote_authority),
            ("malformed scp authority", malformed_scp_authority),
            ("zero SSH port", zero_ssh_port),
            ("NUL local path", nul_local_path),
        ):
            with self.subTest(name):
                self.write_manifest_document(document)
                result = self.resolve()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.error_code(result), "MANIFEST_INVALID")

    def test_http_remote_does_not_match_https_manifest_identity(self) -> None:
        git(
            self.consumer,
            "remote",
            "set-url",
            "origin",
            "http://github.com/systalyze/systalyze.git",
        )
        self.write_manifest(["https://github.com/systalyze/systalyze.git"])

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "REMOTE_IDENTITY_MISMATCH")

    def test_github_repository_path_identity_is_case_insensitive(self) -> None:
        resolver = load_resolver_module()
        scp_prefix = "git" + chr(64) + "github.com:"

        self.assertEqual(
            resolver.normalize_remote_url(scp_prefix + "SYSTALYZE/SYSTALYZE.git"),
            resolver.normalize_remote_url(scp_prefix + "systalyze/systalyze.git"),
        )

    def test_default_remote_ports_are_normalized(self) -> None:
        resolver = load_resolver_module()
        at_sign = chr(64)

        for implicit, explicit in (
            (
                "https://github.com/systalyze/systalyze.git",
                "https://github.com:443/systalyze/systalyze.git",
            ),
            (
                f"ssh://git{at_sign}github.com/systalyze/systalyze.git",
                f"ssh://git{at_sign}github.com:22/systalyze/systalyze.git",
            ),
        ):
            with self.subTest(explicit=explicit):
                self.assertEqual(
                    resolver.normalize_remote_url(explicit),
                    resolver.normalize_remote_url(implicit),
                )

    def test_remote_identity_rejects_embedded_credentials_and_url_metadata(
        self,
    ) -> None:
        resolver = load_resolver_module()
        at_sign = chr(64)
        host = "example.com"

        for remote_url in (
            f"https://user{at_sign}{host}/systalyze/systalyze.git",
            f"https://user:value{at_sign}{host}/systalyze/systalyze.git",
            f"https://{host}/systalyze/systalyze.git?tracking=value",
            f"https://{host}/systalyze/systalyze.git#section",
            f"ssh://git:value{at_sign}{host}/systalyze/systalyze.git",
            f"ssh://git{at_sign}{host}/systalyze/systalyze.git?tracking=value",
            f"ssh://git{at_sign}{host}/systalyze/systalyze.git#section",
        ):
            with self.subTest(remote_url=remote_url):
                self.assertIsNone(resolver.normalize_remote_url(remote_url))

        self.assertEqual(
            resolver.normalize_remote_url(
                f"git{at_sign}{host}:systalyze/systalyze.git"
            ),
            resolver.normalize_remote_url(
                f"ssh://git{at_sign}{host}/systalyze/systalyze.git"
            ),
        )
        self.assertNotEqual(
            resolver.normalize_remote_url(
                f"ssh://other{at_sign}{host}/systalyze/systalyze.git"
            ),
            resolver.normalize_remote_url(
                f"ssh://git{at_sign}{host}/systalyze/systalyze.git"
            ),
        )

    def test_remote_port_is_part_of_verified_identity(self) -> None:
        git(
            self.consumer,
            "remote",
            "set-url",
            "origin",
            "ssh://git@github.com:2222/systalyze/systalyze.git",
        )
        self.write_manifest(["ssh://git@github.com/systalyze/systalyze.git"])

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "REMOTE_IDENTITY_MISMATCH")

    def test_repository_identity_must_match_network_remote(self) -> None:
        resolver = load_resolver_module()

        with self.assertRaises(resolver.ContractError) as raised:
            resolver.verify_repository_identity(
                "example.invalid/systalyze/systalyze",
                "https://github.com/systalyze/systalyze",
            )

        self.assertEqual(raised.exception.code, "REMOTE_IDENTITY_MISMATCH")

    def test_pull_request_identity_change_during_resolution_fails_closed(self) -> None:
        final_pull_requests = self.pull_requests.with_name("pull-requests-after.json")
        document = json.loads(self.pull_requests.read_text(encoding="utf-8"))
        document[0]["number"] = 303
        final_pull_requests.write_text(json.dumps(document) + "\n", encoding="utf-8")

        result = self.resolve(final_pull_requests=final_pull_requests)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "PR_CHANGED_DURING_RESOLUTION")

    def test_nonidentity_pull_request_change_does_not_invalidate_resolution(
        self,
    ) -> None:
        final_pull_requests = self.pull_requests.with_name("pull-requests-after.json")
        document = json.loads(self.pull_requests.read_text(encoding="utf-8"))
        document[0]["baseRefOid"] = self.unrelated
        document[0]["isDraft"] = True
        final_pull_requests.write_text(json.dumps(document) + "\n", encoding="utf-8")

        result = self.resolve(final_pull_requests=final_pull_requests)

        self.assertEqual(result.returncode, 0, result.stderr)
        resolved = json.loads(result.stdout)
        pull_request = resolved["surfaces"]["grounding-docs"]["pullRequest"]
        self.assertEqual(pull_request["baseRefOid"], self.unrelated)
        self.assertTrue(pull_request["isDraft"])

    def test_alias_move_during_resolution_fails_closed(self) -> None:
        result = self.resolve(
            alias_move=("refs/heads/ivan/stack-tips/dev-tooling", self.unrelated)
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "ALIAS_CHANGED_DURING_RESOLUTION")

    def test_command_failure_reports_only_safe_process_evidence(self) -> None:
        self.remote.rename(self.remote.with_name("unavailable.git"))

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "ALIAS_QUERY_FAILED")
        evidence = self.error_document(result)["error"]["evidence"]
        self.assertEqual(set(evidence), {"returnCode", "stdoutSha256", "stderrSha256"})
        self.assertRegex(evidence["stdoutSha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(evidence["stderrSha256"], r"^sha256:[0-9a-f]{64}$")

    def test_missing_gh_returns_a_json_error_envelope(self) -> None:
        result = self.resolve(missing_gh=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "PR_QUERY_FAILED")
        evidence = self.error_document(result)["error"]["evidence"]
        self.assertEqual(evidence, {"command": "gh", "osError": "FileNotFoundError"})

    def test_nonobject_pull_request_entry_fails_closed(self) -> None:
        self.pull_requests.write_text("[null]\n", encoding="utf-8")

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "PR_QUERY_INVALID")

    def test_maximum_pull_request_page_fails_as_truncated(self) -> None:
        document = json.loads(self.pull_requests.read_text(encoding="utf-8"))
        document.extend({"number": number} for number in range(3, 1001))
        self.pull_requests.write_text(json.dumps(document) + "\n", encoding="utf-8")

        result = self.resolve()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.error_code(result), "PR_QUERY_TRUNCATED")

    def test_command_runner_is_bounded_and_noninteractive(self) -> None:
        resolver = load_resolver_module()
        with mock.patch.dict(
            os.environ,
            {
                "GIT_SSH_COMMAND": "LC_ALL=C ssh -F 'fixture config'",
                "GIT_DIR": str(self.remote),
                "GIT_WORK_TREE": str(self.provider),
                "GIT_COMMON_DIR": str(self.remote),
                "GIT_INDEX_FILE": str(self.remote / "fixture-index"),
                "GIT_EXEC_PATH": str(self.fake_bin),
                "GIT_OBJECT_DIRECTORY": str(self.remote / "objects"),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(
                    self.unrelated_provider / ".git" / "objects"
                ),
            },
            clear=False,
        ):
            environment_check = resolver.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os; "
                        "print(os.environ['GIT_TERMINAL_PROMPT'], "
                        "os.environ['GIT_ASKPASS'], "
                        "os.environ['GCM_INTERACTIVE'], "
                        "os.environ['GH_PROMPT_DISABLED'], "
                        "os.environ['SSH_ASKPASS'], "
                        "os.environ['SSH_ASKPASS_REQUIRE']); "
                        "print(os.environ['GIT_SSH_COMMAND']); "
                        "print(any(name in os.environ for name in ("
                        "'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', "
                        "'GIT_INDEX_FILE', 'GIT_EXEC_PATH', 'GIT_OBJECT_DIRECTORY', "
                        "'GIT_ALTERNATE_OBJECT_DIRECTORIES')))"
                    ),
                ],
                cwd=self.consumer,
                failure_code="ENVIRONMENT_CHECK_FAILED",
                timeout_seconds=30,
                uses_ssh_transport=True,
            )
        self.assertEqual(
            environment_check.stdout.strip(),
            "0 false never 1 false never\n"
            "LC_ALL=C ssh -o BatchMode=yes -F 'fixture config'\n"
            "False",
        )

        with mock.patch.dict(
            os.environ, {"GIT_SSH_COMMAND": "ssh -o BatchMode=no"}, clear=False
        ):
            batch_mode_override = resolver.run(
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ['GIT_SSH_COMMAND'])",
                ],
                cwd=self.consumer,
                failure_code="ENVIRONMENT_CHECK_FAILED",
                timeout_seconds=30,
                uses_ssh_transport=True,
            )
        self.assertEqual(
            batch_mode_override.stdout.strip(),
            "ssh -o BatchMode=yes -o BatchMode=no",
        )

        with mock.patch.dict(
            os.environ,
            {"GIT_SSH_COMMAND": "plink -P 22"},
            clear=False,
        ):
            putty_command = resolver.run(
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ['GIT_SSH_COMMAND'])",
                ],
                cwd=self.consumer,
                failure_code="ENVIRONMENT_CHECK_FAILED",
                timeout_seconds=30,
                uses_ssh_transport=True,
            )
        self.assertEqual(putty_command.stdout.strip(), "plink -batch -P 22")

        with self.assertRaises(resolver.ContractError) as raised:
            resolver.run(
                [sys.executable, "-c", "import time; time.sleep(1)"],
                cwd=self.consumer,
                failure_code="COMMAND_TIMED_OUT",
                timeout_seconds=0.01,
            )
        self.assertEqual(raised.exception.code, "COMMAND_TIMED_OUT")
        self.assertEqual(
            raised.exception.evidence,
            {"command": Path(sys.executable).name, "timeoutSeconds": 0.01},
        )

    def test_command_runner_disables_lazy_fetch(self) -> None:
        resolver = load_resolver_module()

        environment_check = resolver.run(
            [
                sys.executable,
                "-c",
                "import os; print(os.environ['GIT_NO_LAZY_FETCH'])",
            ],
            cwd=self.consumer,
            failure_code="ENVIRONMENT_CHECK_FAILED",
        )

        self.assertEqual(environment_check.stdout.strip(), "1")

    def test_destination_bound_ssh_uses_trusted_executable(self) -> None:
        resolver = load_resolver_module()
        fake_ssh = self.fake_bin / "ssh"
        fake_ssh.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
        fake_ssh.chmod(0o755)

        with mock.patch.dict(
            os.environ,
            {
                "GIT_SSH_COMMAND": "ssh",
                "PATH": str(self.fake_bin) + os.pathsep + os.environ["PATH"],
            },
            clear=False,
        ):
            environment_check = resolver.run(
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ['GIT_SSH_COMMAND'])",
                ],
                cwd=self.consumer,
                failure_code="ENVIRONMENT_CHECK_FAILED",
                uses_ssh_transport=True,
                ssh_destination=("github.com", 22),
            )

        self.assertEqual(
            shlex.split(environment_check.stdout.strip())[0],
            "/usr/bin/ssh",
        )

    def test_destination_bound_ssh_rejects_lookalike_and_wrapper(self) -> None:
        resolver = load_resolver_module()
        fake_ssh = self.fake_bin / "ssh"
        fake_ssh.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
        fake_ssh.chmod(0o755)

        for ssh_command, evidence_key in (
            (str(fake_ssh), "sshExecutableUntrusted"),
            ("env FIXTURE=value ssh", "sshCommandUnsupported"),
        ):
            with self.subTest(ssh_command=ssh_command):
                with (
                    mock.patch.dict(
                        os.environ,
                        {"GIT_SSH_COMMAND": ssh_command},
                        clear=False,
                    ),
                    self.assertRaises(resolver.ContractError) as raised,
                ):
                    resolver.run(
                        [sys.executable, "-c", "raise SystemExit(0)"],
                        cwd=self.consumer,
                        failure_code="SSH_CONFIGURATION_FAILED",
                        uses_ssh_transport=True,
                        ssh_destination=("github.com", 22),
                    )

                self.assertEqual(
                    raised.exception.code,
                    "SSH_CONFIGURATION_FAILED",
                )
                self.assertEqual(raised.exception.evidence[evidence_key], True)

    def test_command_runner_hashes_invalid_failure_output_as_bytes(self) -> None:
        resolver = load_resolver_module()

        with self.assertRaises(resolver.ContractError) as raised:
            resolver.run(
                [
                    sys.executable,
                    "-c",
                    "import os; os.write(2, b'\\xff'); raise SystemExit(7)",
                ],
                cwd=self.consumer,
                failure_code="INVALID_OUTPUT_FAILED",
            )

        self.assertEqual(raised.exception.code, "INVALID_OUTPUT_FAILED")
        self.assertEqual(raised.exception.evidence["returnCode"], 7)
        self.assertRegex(
            cast(str, raised.exception.evidence["stdoutSha256"]),
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertRegex(
            cast(str, raised.exception.evidence["stderrSha256"]),
            r"^sha256:[0-9a-f]{64}$",
        )

    def test_command_runner_wraps_invalid_success_output(self) -> None:
        resolver = load_resolver_module()

        with self.assertRaises(resolver.ContractError) as raised:
            resolver.run(
                [
                    sys.executable,
                    "-c",
                    "import os; os.write(1, b'\\xff')",
                ],
                cwd=self.consumer,
                failure_code="INVALID_OUTPUT_FAILED",
            )

        self.assertEqual(raised.exception.code, "INVALID_OUTPUT_FAILED")
        self.assertEqual(raised.exception.evidence["outputEncodingInvalid"], True)
        self.assertRegex(
            cast(str, raised.exception.evidence["stdoutSha256"]),
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertRegex(
            cast(str, raised.exception.evidence["stderrSha256"]),
            r"^sha256:[0-9a-f]{64}$",
        )

    def test_command_timeout_terminates_descendants(self) -> None:
        resolver = load_resolver_module()
        ready = self.consumer.parent / "descendant-ready"
        marker = self.consumer.parent / "descendant-survived"
        descendant = (
            "import pathlib,signal,time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"pathlib.Path({str(ready)!r}).touch(); time.sleep(0.6); "
            f"pathlib.Path({str(marker)!r}).write_text('alive', encoding='utf-8')"
        )
        parent = (
            "import pathlib,subprocess,sys,time\n"
            "subprocess.Popen([sys.executable, '-c', sys.argv[1]], "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL)\n"
            "ready = pathlib.Path(sys.argv[2])\n"
            "while not ready.exists():\n"
            "    time.sleep(0.005)\n"
            "time.sleep(30)\n"
        )

        with self.assertRaises(resolver.ContractError) as raised:
            resolver.run(
                [sys.executable, "-c", parent, descendant, str(ready)],
                cwd=self.consumer,
                failure_code="COMMAND_TIMED_OUT",
                timeout_seconds=0.2,
            )

        self.assertEqual(raised.exception.code, "COMMAND_TIMED_OUT")
        self.assertTrue(ready.exists())
        time.sleep(0.7)
        self.assertFalse(marker.exists())

    def test_documented_interpreter_isolates_python_startup_and_imports(self) -> None:
        startup = self.consumer.parent / "python-startup"
        startup.mkdir()
        site_marker = self.consumer.parent / "sitecustomize-loaded"
        import_marker = self.consumer.parent / "ambient-argparse-loaded"
        (startup / "sitecustomize.py").write_text(
            f"from pathlib import Path\nPath({str(site_marker)!r}).touch()\n",
            encoding="utf-8",
        )
        (startup / "argparse.py").write_text(
            f"from pathlib import Path\nPath({str(import_marker)!r}).touch()\n"
            "raise RuntimeError('ambient argparse loaded')\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(startup)

        result = subprocess.run(
            ["/usr/bin/python3", "-I", "-S", str(RESOLVER), "--help"],
            cwd=self.consumer,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(site_marker.exists())
        self.assertFalse(import_marker.exists())

    def test_timeout_cleanup_bounds_final_pipe_drain(self) -> None:
        resolver = load_resolver_module()
        process = mock.Mock(
            pid=12345,
            stdout=mock.Mock(),
            stderr=mock.Mock(),
        )
        process.communicate.side_effect = subprocess.TimeoutExpired(
            cmd="fixture",
            timeout=0.05,
        )
        process.wait.side_effect = subprocess.TimeoutExpired(
            cmd="fixture",
            timeout=0.05,
        )

        with mock.patch.object(resolver.os, "killpg") as kill_group:
            resolver.terminate_process_group(process)

        self.assertEqual(
            kill_group.call_args_list,
            [
                mock.call(process.pid, signal.SIGTERM),
                mock.call(process.pid, signal.SIGKILL),
            ],
        )
        process.stdout.close.assert_called_once_with()
        process.stderr.close.assert_called_once_with()
        process.wait.assert_called_once_with(
            timeout=resolver.PROCESS_TERMINATION_GRACE_SECONDS,
        )

    def test_openssh_destination_is_pinned_before_configured_overrides(self) -> None:
        resolver = load_resolver_module()
        ssh_config = self.consumer.parent / "ssh-config"
        ssh_config.write_text(
            "Host github.com\n"
            "  HostName mirror.invalid\n"
            "  Port 2222\n"
            "  ProxyCommand nc proxy.invalid 2222\n",
            encoding="utf-8",
        )
        command = resolver.noninteractive_ssh_command(
            f"ssh -F {shlex.quote(str(ssh_config))} "
            "-o HostName=other.invalid -o Port=3333 "
            "-o ProxyJump=jump.invalid",
            failure_code="SSH_CONFIGURATION_FAILED",
            command_name="git",
            ssh_destination=("github.com", 22),
        )

        effective = run(
            *shlex.split(command),
            "-G",
            "github.com",
            cwd=self.consumer,
        )
        settings = dict(
            line.split(maxsplit=1)
            for line in effective.stdout.splitlines()
            if " " in line
        )
        self.assertEqual(settings["hostname"], "github.com")
        self.assertEqual(settings["port"], "22")
        self.assertNotIn("proxycommand", settings)
        self.assertNotIn("proxyjump", settings)

    def test_plink_destination_changing_configuration_fails_closed(self) -> None:
        resolver = load_resolver_module()

        with (
            mock.patch.dict(
                os.environ,
                {"GIT_SSH_COMMAND": "plink -load mirror"},
                clear=False,
            ),
            self.assertRaises(resolver.ContractError) as raised,
        ):
            resolver.run(
                [sys.executable, "-c", "raise SystemExit(0)"],
                cwd=self.consumer,
                failure_code="SSH_CONFIGURATION_FAILED",
                uses_ssh_transport=True,
                ssh_destination=("github.com", 22),
            )

        self.assertEqual(raised.exception.code, "SSH_CONFIGURATION_FAILED")
        self.assertEqual(raised.exception.evidence["sshCommandUnsupported"], True)

    def test_immutable_fetch_disables_automatic_maintenance(self) -> None:
        resolver = load_resolver_module()
        completed = subprocess.CompletedProcess(
            args=["git"],
            returncode=0,
            stdout="",
            stderr="",
        )

        with mock.patch.object(resolver, "git", return_value=completed) as git_command:
            resolver.fetch_immutable_objects(
                self.remote,
                self.consumer / ".git" / "objects",
                self.remote.as_uri(),
                {"grounding-docs": self.grounding},
                negotiation_tips=(self.base,),
                uses_ssh_transport=False,
                ssh_destination=None,
                git_config_snapshot=(),
            )

        self.assertIn("--no-auto-gc", git_command.call_args_list[0].args)
        self.assertIn(
            f"--negotiation-tip={self.base}",
            git_command.call_args_list[0].args,
        )

    def test_command_runner_preserves_ssh_command_without_transport_mode(self) -> None:
        resolver = load_resolver_module()
        with mock.patch.dict(
            os.environ,
            {"GIT_SSH_COMMAND": "custom-ssh-wrapper --mode fixture"},
            clear=False,
        ):
            environment_check = resolver.run(
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ['GIT_SSH_COMMAND'])",
                ],
                cwd=self.consumer,
                failure_code="ENVIRONMENT_CHECK_FAILED",
                timeout_seconds=30,
            )

        self.assertEqual(
            environment_check.stdout.strip(),
            "custom-ssh-wrapper --mode fixture",
        )

    def test_command_runner_preserves_configured_ssh_command(self) -> None:
        resolver = load_resolver_module()
        git(
            self.consumer,
            "config",
            "core.sshCommand",
            "ssh -F 'fixture config'",
        )

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GIT_SSH_COMMAND", None)
            environment_check = resolver.run(
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ['GIT_SSH_COMMAND'])",
                ],
                cwd=self.consumer,
                failure_code="ENVIRONMENT_CHECK_FAILED",
                timeout_seconds=30,
                uses_ssh_transport=True,
            )

        self.assertEqual(
            environment_check.stdout.strip(),
            "ssh -o BatchMode=yes -F 'fixture config'",
        )

    def test_ssh_command_enforces_host_key_verification(self) -> None:
        resolver = load_resolver_module()
        ssh_config = self.consumer.parent / "ssh-config"
        ssh_config.write_text(
            "Host github.com\n"
            "  StrictHostKeyChecking no\n"
            "  HostKeyAlias mirror.invalid\n"
            "  UserKnownHostsFile /dev/null\n"
            "  ControlMaster auto\n"
            f"  ControlPath {self.consumer.parent / 'configured-control'}\n",
            encoding="utf-8",
        )
        configured = (
            f"/usr/bin/ssh -F {shlex.quote(str(ssh_config))} "
            "-o StrictHostKeyChecking=no "
            "-o HostKeyAlias=argument.invalid "
            f"-S {shlex.quote(str(self.consumer.parent / 'argument-control'))}"
        )

        hardened = resolver.noninteractive_ssh_command(
            configured,
            failure_code="SSH_CONFIGURATION_FAILED",
            command_name="git",
            ssh_destination=("github.com", 22),
        )
        result = subprocess.run(
            [*shlex.split(hardened), "-G", "github.com"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        settings = dict(
            line.split(maxsplit=1) for line in result.stdout.splitlines() if " " in line
        )
        self.assertEqual(settings["stricthostkeychecking"], "true")
        self.assertEqual(settings["hostkeyalias"], "github.com")
        self.assertNotIn("controlpath", settings)

    def test_ssh_command_pins_port_qualified_host_key_alias(self) -> None:
        resolver = load_resolver_module()
        configured = (
            "/usr/bin/ssh -o HostName=mirror.invalid "
            "-o Port=9999 -o HostKeyAlias=mirror.invalid"
        )

        hardened = resolver.noninteractive_ssh_command(
            configured,
            failure_code="SSH_CONFIGURATION_FAILED",
            command_name="git",
            ssh_destination=("github.com", 2222),
        )
        result = subprocess.run(
            [*shlex.split(hardened), "-G", "github.com"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        settings = dict(
            line.split(maxsplit=1) for line in result.stdout.splitlines() if " " in line
        )
        self.assertEqual(settings["hostname"], "github.com")
        self.assertEqual(settings["port"], "2222")
        self.assertEqual(settings["hostkeyalias"], "[github.com]:2222")

    def test_configured_ssh_command_preserves_literal_arguments_in_git_transport(
        self,
    ) -> None:
        resolver = load_resolver_module()
        fixture_home = self.consumer.parent / "fixture home"
        fixture_home.mkdir()
        fixture_config = fixture_home / "fixture config"
        fixture_config.write_text("", encoding="utf-8")
        ssh_arguments = self.consumer.parent / "ssh-arguments.json"
        fake_ssh = self.fake_bin / "ssh"
        fake_ssh.write_text(
            """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

arguments = sys.argv[1:]
if os.environ.get("FIXTURE_TRANSPORT") not in {"configured transport", "ambient"}:
    raise SystemExit(3)
Path(os.environ["FIXTURE_SSH_ARGUMENTS"]).write_text(
    json.dumps(arguments), encoding="utf-8"
)
index = 0
while index < len(arguments) and arguments[index].startswith("-"):
    index += 2 if arguments[index] in {"-F", "-i", "-o", "-p"} else 1
if len(arguments) - index != 2:
    raise SystemExit(2)
os.execl("/bin/sh", "sh", "-c", arguments[index + 1])
""",
            encoding="utf-8",
        )
        fake_ssh.chmod(0o755)
        git(
            self.consumer,
            "config",
            "core.sshCommand",
            "FIXTURE_TRANSPORT='configured transport' ssh "
            f"-F {shlex.quote(str(fixture_config))}",
        )
        environment = {
            "FIXTURE_SSH_ARGUMENTS": str(ssh_arguments),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "HOME": str(fixture_home),
            "PATH": str(self.fake_bin) + os.pathsep + os.environ["PATH"],
        }
        remote_url = f"ssh://fixture{self.remote}"

        with mock.patch.dict(os.environ, environment, clear=False):
            os.environ.pop("GIT_SSH_COMMAND", None)
            resolver.run(
                ["git", "ls-remote", remote_url],
                cwd=self.consumer,
                failure_code="SSH_TRANSPORT_FAILED",
                uses_ssh_transport=True,
            )

        self.assertEqual(
            json.loads(ssh_arguments.read_text(encoding="utf-8"))[:5],
            ["-o", "BatchMode=yes", "-F", str(fixture_config), "fixture"],
        )

        with mock.patch.dict(
            os.environ,
            {
                **environment,
                "GIT_SSH_COMMAND": (
                    "env FIXTURE_TRANSPORT=ambient ssh "
                    f"-F {shlex.quote(str(fixture_home / 'ambient config'))}"
                ),
            },
            clear=False,
        ):
            resolver.run(
                ["git", "ls-remote", remote_url],
                cwd=self.consumer,
                failure_code="SSH_TRANSPORT_FAILED",
                uses_ssh_transport=True,
            )

        self.assertEqual(
            json.loads(ssh_arguments.read_text(encoding="utf-8"))[:5],
            [
                "-o",
                "BatchMode=yes",
                "-F",
                str(fixture_home / "ambient config"),
                "fixture",
            ],
        )

    def test_command_runner_rejects_unsafe_ssh_commands(self) -> None:
        resolver = load_resolver_module()
        for ssh_command, evidence_key in (
            ("", "sshCommandInvalid"),
            ("ssh\nssh", "sshCommandUnsupported"),
            ("ssh\rssh", "sshCommandUnsupported"),
            ("ssh; ssh", "sshCommandUnsupported"),
            ("custom-ssh-wrapper --mode fixture", "sshCommandUnsupported"),
            ("env --split-string ssh", "sshCommandUnsupported"),
            ("env -u", "sshCommandInvalid"),
            ("'x=y' ssh", "sshCommandUnsupported"),
            ('"x=y" ssh', "sshCommandUnsupported"),
            (r"x\=y ssh", "sshCommandUnsupported"),
            ("x'='y ssh", "sshCommandUnsupported"),
            ("LC_ALL=C 'x=y' ssh", "sshCommandUnsupported"),
            ('"$HOME/bin/ssh"', "sshCommandUnsupported"),
            ("`helper`/ssh", "sshCommandUnsupported"),
            ("*/ssh", "sshCommandUnsupported"),
            ('ssh -F "$HOME/config"', "sshCommandUnsupported"),
            ("ssh `helper`", "sshCommandUnsupported"),
            ("HOME=~ ssh", "sshCommandUnsupported"),
            ("ssh -F {one,two}", "sshCommandUnsupported"),
            ("ssh -F config # comment", "sshCommandUnsupported"),
        ):
            with (
                self.subTest(ssh_command=repr(ssh_command)),
                mock.patch.dict(
                    os.environ,
                    {"GIT_SSH_COMMAND": ssh_command},
                    clear=False,
                ),
            ):
                with self.assertRaises(resolver.ContractError) as raised:
                    resolver.run(
                        [sys.executable, "-c", "raise SystemExit(0)"],
                        cwd=self.consumer,
                        failure_code="ENVIRONMENT_CHECK_FAILED",
                        uses_ssh_transport=True,
                    )

                self.assertEqual(raised.exception.code, "ENVIRONMENT_CHECK_FAILED")
                self.assertEqual(
                    raised.exception.evidence,
                    {
                        "command": Path(sys.executable).name,
                        evidence_key: True,
                    },
                )

        git(self.consumer, "config", "core.sshCommand", "")
        with (
            mock.patch.dict(os.environ, {}, clear=False),
            self.assertRaises(resolver.ContractError) as raised,
        ):
            os.environ.pop("GIT_SSH_COMMAND", None)
            resolver.run(
                [sys.executable, "-c", "raise SystemExit(0)"],
                cwd=self.consumer,
                failure_code="ENVIRONMENT_CHECK_FAILED",
                uses_ssh_transport=True,
            )

        self.assertEqual(raised.exception.code, "ENVIRONMENT_CHECK_FAILED")
        self.assertEqual(
            raised.exception.evidence,
            {
                "command": Path(sys.executable).name,
                "sshCommandInvalid": True,
            },
        )

    def test_ssh_parser_normalizes_static_assignment_and_env_forms(self) -> None:
        resolver = load_resolver_module()
        for ssh_command, expected in (
            ("x=y ssh", "x=y ssh -o BatchMode=yes"),
            ("x='y z' ssh", "x='y z' ssh -o BatchMode=yes"),
            ("x=a=~ ssh", "x='a=~' ssh -o BatchMode=yes"),
            ("x={one,two} ssh", "x='{one,two}' ssh -o BatchMode=yes"),
            ("x=y Y=z ssh", "x=y Y=z ssh -o BatchMode=yes"),
            ("env 'x=y' ssh", "env x=y ssh -o BatchMode=yes"),
            ("env HOME=~ ssh", "env 'HOME=~' ssh -o BatchMode=yes"),
            ("env -i x=y ssh", "env -i x=y ssh -o BatchMode=yes"),
        ):
            with self.subTest(ssh_command=ssh_command):
                self.assertEqual(
                    resolver.noninteractive_ssh_command(
                        ssh_command,
                        failure_code="ENVIRONMENT_CHECK_FAILED",
                        command_name="git",
                    ),
                    expected,
                )

    def test_does_not_accept_file_backed_contract_overrides(self) -> None:
        for flag, value in (
            ("--manifest", self.manifest),
            ("--pr-json", self.pull_requests),
        ):
            with self.subTest(flag):
                result = run(
                    sys.executable,
                    str(RESOLVER),
                    "--repo",
                    str(self.consumer),
                    flag,
                    str(value),
                    cwd=self.consumer,
                    check=False,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"unrecognized arguments: {flag}", result.stderr)


if __name__ == "__main__":
    unittest.main()
