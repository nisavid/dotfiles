from __future__ import annotations

import importlib.util
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import types
import unittest
from unittest import mock


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SOURCE_TEMPLATE = (
    ROOT
    / "home/private_dot_local/lib/hindsight-runtime/sitecustomize.py.tmpl"
)
_SOURCE_PHASE = tempfile.TemporaryDirectory()
SOURCE = Path(_SOURCE_PHASE.name) / "sitecustomize.py"
source_descriptor = os.open(
    SOURCE,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
    0o600,
)
with os.fdopen(source_descriptor, "w") as rendered_source:
    subprocess.run(
        ["chezmoi", "-S", str(ROOT / "home"), "execute-template"],
        check=True,
        input=SOURCE_TEMPLATE.read_text(),
        stdout=rendered_source,
        text=True,
    )
SPEC = importlib.util.spec_from_file_location("hindsight_sitecustomize", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HindsightProviderBindingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reads_the_same_protected_descriptor_it_validates(self) -> None:
        path = self.root / "policy.json"
        path.write_bytes(b'{"schema_version":1}')
        path.chmod(0o600)

        self.assertEqual(
            MODULE._read_protected_file(path, "policy"),
            b'{"schema_version":1}',
        )
        path.chmod(0o640)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._read_protected_file(path, "policy")

    def test_rejects_symlinks_and_multiple_hard_links(self) -> None:
        path = self.root / "auth.json"
        path.write_bytes(b"{}")
        path.chmod(0o600)
        link = self.root / "auth-link.json"
        link.symlink_to(path)
        with self.assertRaises(OSError):
            MODULE._read_protected_file(link, "auth")

        hardlink = self.root / "auth-hardlink.json"
        os.link(path, hardlink)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._read_protected_file(path, "auth")

    def test_rejects_writable_release_directories(self) -> None:
        release = self.root / "release"
        release.mkdir(mode=0o700)
        MODULE._protected_directory(release, "release")
        release.chmod(0o720)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._protected_directory(release, "release")

    def test_active_release_record_is_exact_and_bounded(self) -> None:
        install_root = self.root / "install"
        releases_root = install_root / "releases"
        release_digest = "a" * 64
        release = releases_root / f"1.0.0-{release_digest[:16]}"
        (release / "lib").mkdir(parents=True)
        active = install_root / "active.json"
        record = {
            "version": "1.0.0",
            "release_digest": release_digest,
            "release_path": f"releases/{release.name}",
        }
        active.write_text(json.dumps(record))
        active.chmod(0o600)

        self.assertEqual(
            MODULE._resolve_active_release(install_root),
            release.resolve(strict=True),
        )

        for label, mutation in (
            ("extra-key", {**record, "unexpected": True}),
            ("outside", {**record, "release_path": "../outside"}),
            (
                "wrong-name",
                {**record, "release_path": "releases/not-the-record"},
            ),
        ):
            with self.subTest(label=label):
                active.write_text(json.dumps(mutation))
                active.chmod(0o600)
                with self.assertRaises(RuntimeError):
                    MODULE._resolve_active_release(install_root)

    def test_production_shaped_startup_uses_active_json(self) -> None:
        home = self.root / "home"
        home.mkdir(mode=0o700)
        install_root = home / MODULE._INSTALL_ROOT
        release_digest = "b" * 64
        release = (
            install_root
            / "releases"
            / f"1.0.0-{release_digest[:16]}"
        )
        release_lib = release / "lib"
        control_package = release_lib / "hindsight_memory_control_plane"
        control_package.mkdir(parents=True)
        (control_package / "__init__.py").write_text("")
        (control_package / "canonical.py").write_text(
            "import json\nstrict_json_loads = json.loads\n"
        )
        (control_package / "provider_runtime.py").write_text(
            "class Member:\n"
            "    id = 'member-primary'\n"
            "    credential_mode = 'oauth-home'\n"
            "    credential_locator = 'home-relative:.fixture/primary'\n"
            "class ProviderRuntimePolicy:\n"
            "    failover_order = ('member-primary',)\n"
            "    embedding_failover_order = "
            "('member-primary', 'member-secondary')\n"
            "    @classmethod\n"
            "    def load(cls, value):\n"
            "        return cls()\n"
            "    def member(self, member_id):\n"
            "        return Member()\n"
            "class HindsightProviderAdapter:\n"
            "    def __init__(self, policy, credential_resolver):\n"
            "        pass\n"
            "    def install(self):\n"
            "        pass\n"
        )
        bootstrap = self.root / "bootstrap"
        providers = bootstrap / "hindsight_api/engine/providers"
        providers.mkdir(parents=True)
        for package in (
            bootstrap / "hindsight_api",
            bootstrap / "hindsight_api/engine",
            providers,
        ):
            (package / "__init__.py").write_text("")
        (bootstrap / "hindsight_api/engine/embeddings.py").write_text(
            "class Embeddings:\n"
            "    pass\n"
            "class CodexOAuthEmbeddings:\n"
            "    pass\n"
        )
        (providers / "codex_auth.py").write_text(
            "class CodexRefreshExpiredError(RuntimeError):\n"
            "    pass\n"
            "class CodexAuthManager:\n"
            "    def refresh_tokens(self, reason='', *, force=False):\n"
            "        pass\n"
            "    def _token_is_stale(self, skew_seconds=60):\n"
            "        return False\n"
        )
        (providers / "codex_llm.py").write_text(
            "class CodexLLM:\n"
            "    def __init__(self):\n"
            "        self._auth_manager = None\n"
            "    async def _refresh_oauth_tokens("
            "self, reason='', *, force=False):\n"
            "        pass\n"
            "    async def call(self):\n"
            "        pass\n"
            "    async def call_with_tools(self):\n"
            "        pass\n"
        )
        active = install_root / "active.json"
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "release_digest": release_digest,
                    "release_path": (
                        f"releases/{release.name}"
                    ),
                }
            )
        )
        active.chmod(0o600)
        policy = (
            home
            / MODULE._PROVIDER_POLICY_PATH
        )
        policy.parent.mkdir(parents=True)
        policy.write_text("{}")
        policy.chmod(0o600)

        environment = {
            **os.environ,
            "HOME": str(home),
            "HINDSIGHT_CODEX_TERMINAL_AUTH_COOLDOWN_SECONDS": "300",
            "HINDSIGHT_EMBEDDING_FAILOVER_ORDER": (
                "member-primary,member-secondary"
            ),
            "PYTHONPATH": str(bootstrap),
        }
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import runpy; "
                    f"runpy.run_path({str(SOURCE)!r}, run_name='__main__')"
                ),
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((install_root / "active").exists())

    def test_policy_path_ignores_environment_override(self) -> None:
        previous = os.environ.get("HINDSIGHT_PROVIDER_POLICY_PATH")
        os.environ["HINDSIGHT_PROVIDER_POLICY_PATH"] = str(
            self.root / "untrusted-policy.json"
        )
        try:
            self.assertEqual(
                MODULE._provider_policy_path(self.root),
                self.root / MODULE._PROVIDER_POLICY_PATH,
            )
        finally:
            if previous is None:
                os.environ.pop("HINDSIGHT_PROVIDER_POLICY_PATH", None)
            else:
                os.environ["HINDSIGHT_PROVIDER_POLICY_PATH"] = previous

    def test_rejects_writable_or_symlinked_oauth_home_ancestry(self) -> None:
        self.root.chmod(0o750)
        parent = self.root / "provider"
        parent.mkdir(mode=0o755)
        oauth_home = parent / "oauth"
        oauth_home.mkdir(mode=0o700)
        MODULE._protected_directory_ancestry(
            oauth_home,
            self.root,
            "OAuth home",
        )
        MODULE._protected_directory(oauth_home, "OAuth home", private=True)

        oauth_home.chmod(0o750)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._protected_directory(oauth_home, "OAuth home", private=True)
        oauth_home.chmod(0o700)

        parent.chmod(0o770)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._protected_directory_ancestry(
                oauth_home,
                self.root,
                "OAuth home",
            )
        parent.chmod(0o755)

        subprocess.run(
            ["/bin/chmod", "+a", "everyone allow read,write", oauth_home],
            check=True,
        )
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._protected_directory(oauth_home, "OAuth home", private=True)
        subprocess.run(["/bin/chmod", "-N", oauth_home], check=True)

        auth = oauth_home / "auth.json"
        auth.write_text("{}")
        auth.chmod(0o600)
        subprocess.run(
            ["/bin/chmod", "+a", "everyone allow read,write", auth],
            check=True,
        )
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._read_protected_file(auth, "OAuth auth")
        subprocess.run(["/bin/chmod", "-N", auth], check=True)

        parent.chmod(0o700)

        link = parent / "oauth-link"
        link.symlink_to(oauth_home, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._protected_directory_ancestry(
                link,
                self.root,
                "OAuth home",
            )

    def test_provider_policy_matches_encrypted_member_order(self) -> None:
        private_data = tomllib.loads(
            subprocess.run(
                [
                    "chezmoi",
                    "decrypt",
                    str(ROOT / "home/.private-hindsight.toml.age"),
                ],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            ).stdout
        )["hindsight"]
        template = (
            ROOT
            / "home/dot_config/private_hindsight-control-plane/"
            "private_provider-runtime-policy.json.tmpl"
        ).read_text()
        policy = json.loads(
            subprocess.run(
                ["chezmoi", "-S", str(ROOT / "home"), "execute-template"],
                check=True,
                input=template,
                stdout=subprocess.PIPE,
                text=True,
            ).stdout
        )
        failover_order = policy["failover_order"]
        member_ids = [member["id"] for member in policy["members"]]

        self.assertEqual(failover_order, private_data["failoverOrder"])
        self.assertCountEqual(member_ids, failover_order)
        self.assertNotIn("terminal_auth_cooldown_seconds", policy)
        self.assertNotIn("embedding_failover_order", policy)
        credentials_template = subprocess.run(
            ["chezmoi", "-S", str(ROOT / "home"), "execute-template"],
            check=True,
            input=(
                ROOT
                / "home/.chezmoitemplates/"
                "hindsight-stack-credentials-environment.tmpl"
            ).read_text(),
            stdout=subprocess.PIPE,
            text=True,
        ).stdout
        environment = json.loads(f"{{{credentials_template}}}")["environment"]
        self.assertEqual(
            environment["HINDSIGHT_EMBEDDING_FAILOVER_ORDER"],
            ",".join(private_data["embeddingMemberIds"]),
        )

    def test_cross_process_auth_lock_times_out(self) -> None:
        auth_file = self.root / "codex" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        with (
            mock.patch.object(
                MODULE.fcntl,
                "flock",
                side_effect=BlockingIOError,
            ),
            mock.patch.object(
                MODULE.time,
                "monotonic",
                side_effect=(0.0, MODULE._AUTH_LOCK_TIMEOUT_SECONDS + 1.0),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Timed out acquiring"):
                with MODULE._exclusive_auth_lock(auth_file):
                    self.fail("lock should not have been acquired")

    def test_interrupted_auth_lock_obeys_the_same_deadline(self) -> None:
        auth_file = self.root / "interrupted-codex" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        with (
            mock.patch.object(
                MODULE.fcntl,
                "flock",
                side_effect=InterruptedError,
            ),
            mock.patch.object(
                MODULE.time,
                "monotonic",
                side_effect=(0.0, MODULE._AUTH_LOCK_TIMEOUT_SECONDS + 1.0),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Timed out acquiring"):
                with MODULE._exclusive_auth_lock(auth_file):
                    self.fail("lock should not have been acquired")

    def test_stack_enables_seven_day_llm_trace_retention(self) -> None:
        private_data = tomllib.loads(
            subprocess.run(
                [
                    "chezmoi",
                    "decrypt",
                    str(ROOT / "home/.private-hindsight.toml.age"),
                ],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            ).stdout
        )["hindsight"]
        rendered = subprocess.run(
            ["chezmoi", "-S", str(ROOT / "home"), "execute-template"],
            check=True,
            input=(
                ROOT
                / "home/.chezmoitemplates/"
                "hindsight-stack-credentials-environment.tmpl"
            ).read_text(),
            stdout=subprocess.PIPE,
            text=True,
        ).stdout
        environment = json.loads(f"{{{rendered}}}")["environment"]

        self.assertEqual(
            environment["HINDSIGHT_API_LLM_TRACE_ENABLED"],
            str(private_data["llmTraceEnabled"]).lower(),
        )
        self.assertEqual(
            environment["HINDSIGHT_API_LLM_TRACE_RETENTION_DAYS"],
            str(private_data["llmTraceRetentionDays"]),
        )
        self.assertEqual(
            environment["HINDSIGHT_API_AUDIT_LOG_ENABLED"],
            str(private_data["auditLogEnabled"]).lower(),
        )
        self.assertEqual(
            environment["HINDSIGHT_API_AUDIT_LOG_RETENTION_DAYS"],
            str(private_data["auditLogRetentionDays"]),
        )

    def test_codex_manager_rereads_disk_under_cross_process_lock(self) -> None:
        auth_file = self.root / "codex" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": "disk-access",
                        "refresh_token": "disk-refresh",
                        "account_id": "disk-account",
                    },
                }
            )
        )
        auth_file.chmod(0o600)

        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            refresh_calls = 0

            def __init__(self) -> None:
                self.access_token = "stale-access"
                self.refresh_token = "stale-refresh"
                self.account_id = "stale-account"
                self._auth_file = auth_file

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force
                type(self).refresh_calls += 1

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError

        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )
        manager = Manager()
        manager.refresh_tokens(reason="reactive", force=True)

        self.assertEqual(Manager.refresh_calls, 0)
        self.assertEqual(manager.access_token, "disk-access")
        self.assertEqual(manager.refresh_token, "disk-refresh")
        self.assertEqual(manager.account_id, "disk-account")
        lock_file = auth_file.parent / ".hindsight-auth.lock"
        self.assertTrue(lock_file.is_file())
        self.assertEqual(lock_file.stat().st_mode & 0o777, 0o600)

    def test_codex_manager_uses_context_local_auth_file_selector(self) -> None:
        auth_file = self.root / "context-selected" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {"access_token": "context-access"},
                }
            )
        )
        auth_file.chmod(0o600)

        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            def __init__(self, selected_auth_file) -> None:
                self.access_token = "context-access"
                self.refresh_token = None
                self.account_id = None
                self._auth_file = selected_auth_file

            @classmethod
            def from_file(cls, selected_auth_file=None):
                return cls(selected_auth_file)

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError
        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )

        selector = MODULE._CODEX_AUTH_FILE_CONTEXT.set(auth_file)
        try:
            manager = Manager.from_file()
        finally:
            MODULE._CODEX_AUTH_FILE_CONTEXT.reset(selector)

        self.assertEqual(manager._auth_file, auth_file)

    def test_disk_reread_clears_absent_optional_credentials(self) -> None:
        auth_file = self.root / "codex-cleared" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {"access_token": "disk-access"},
                }
            )
        )
        auth_file.chmod(0o600)

        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            def __init__(self) -> None:
                self.access_token = "stale-access"
                self.refresh_token = "stale-refresh"
                self.account_id = "stale-account"
                self._auth_file = auth_file

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError
        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )
        manager = Manager()
        manager.refresh_tokens(reason="reactive", force=True)

        self.assertEqual(manager.access_token, "disk-access")
        self.assertIsNone(manager.refresh_token)
        self.assertIsNone(manager.account_id)

    def test_terminal_refresh_failure_enters_cooldown(self) -> None:
        auth_file = self.root / "codex" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": "same-access",
                        "refresh_token": "same-refresh",
                    },
                }
            )
        )
        auth_file.chmod(0o600)

        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            refresh_calls = 0

            def __init__(self) -> None:
                self.access_token = "same-access"
                self.refresh_token = "same-refresh"
                self.account_id = ""
                self._auth_file = auth_file

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force
                type(self).refresh_calls += 1
                raise TerminalRefreshError("terminal")

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError

        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )
        manager = Manager()
        with self.assertRaises(TerminalRefreshError):
            manager.refresh_tokens(reason="reactive", force=True)
        with self.assertRaisesRegex(
            TerminalRefreshError,
            "temporarily unavailable after terminal authentication failure",
        ):
            manager.refresh_tokens(reason="reactive", force=True)

        self.assertEqual(Manager.refresh_calls, 1)

        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": "reauthorized-access",
                        "refresh_token": "reauthorized-refresh",
                    },
                }
            )
        )
        auth_file.chmod(0o600)
        manager.refresh_tokens(reason="reactive", force=True)

        self.assertEqual(Manager.refresh_calls, 1)
        self.assertEqual(manager.access_token, "reauthorized-access")
        self.assertEqual(manager.refresh_token, "reauthorized-refresh")

    def test_structured_refresh_response_controls_terminal_cooldown(self) -> None:
        cases = (
            (400, {"error": "invalid_grant"}, True),
            (400, {"error": "refresh_token_invalidated"}, True),
            (400, {"error": "refresh_token_reused"}, True),
            (400, {"error": "refresh_token_expired"}, True),
            (400, {"error": "temporarily_unavailable"}, False),
            (500, {"error": "server_error"}, False),
        )
        for index, (status, payload, terminal) in enumerate(cases):
            with self.subTest(status=status, payload=payload):
                auth_file = self.root / f"codex-{index}" / "auth.json"
                auth_file.parent.mkdir(mode=0o700)
                auth_file.write_text(
                    json.dumps(
                        {
                            "auth_mode": "chatgpt",
                            "tokens": {
                                "access_token": "same-access",
                                "refresh_token": "same-refresh",
                            },
                        }
                    )
                )
                auth_file.chmod(0o600)

                class TerminalRefreshError(RuntimeError):
                    pass

                class Response:
                    status_code = status

                    def json(self):
                        return payload

                class Client:
                    calls = 0

                    def post(self, *_args, **_kwargs):
                        type(self).calls += 1
                        return Response()

                class Manager:
                    def __init__(self) -> None:
                        self.access_token = "same-access"
                        self.refresh_token = "same-refresh"
                        self.account_id = ""
                        self._auth_file = auth_file
                        self._http_client = Client()

                    def refresh_tokens(self, reason="", *, force=False):
                        del reason, force
                        response = self._http_client.post("/oauth/token")
                        if response.status_code >= 400:
                            raise RuntimeError(
                                "Codex OAuth refresh failed with "
                                f"HTTP {response.status_code}"
                            )

                    def _token_is_stale(self, skew_seconds=60):
                        del skew_seconds
                        return True

                manager_module = types.ModuleType(
                    "hindsight_api.engine.providers.codex_auth"
                )
                manager_module.CodexAuthManager = Manager
                manager_module.CodexRefreshExpiredError = (
                    TerminalRefreshError
                )
                canonicalize = MODULE._install_codex_auth_runtime(
                    manager_module,
                    cooldown_seconds=300,
                )
                manager = canonicalize(Manager())
                expected_error = (
                    TerminalRefreshError if terminal else RuntimeError
                )
                with self.assertRaises(expected_error):
                    manager.refresh_tokens(reason="reactive", force=True)
                with self.assertRaises(expected_error):
                    manager.refresh_tokens(reason="reactive", force=True)
                self.assertEqual(Client.calls, 1 if terminal else 2)

    def test_missing_refresh_credential_enters_terminal_cooldown(self) -> None:
        auth_file = self.root / "codex" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {"access_token": "same-access"},
                }
            )
        )
        auth_file.chmod(0o600)

        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            refresh_calls = 0

            def __init__(self) -> None:
                self.access_token = "same-access"
                self.refresh_token = None
                self.account_id = ""
                self._auth_file = auth_file

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force
                type(self).refresh_calls += 1

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError
        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )
        manager = Manager()

        with self.assertRaisesRegex(
            TerminalRefreshError,
            "no refresh credential",
        ):
            manager.refresh_tokens(reason="reactive", force=True)
        with self.assertRaisesRegex(
            TerminalRefreshError,
            "temporarily unavailable",
        ):
            manager.refresh_tokens(reason="reactive", force=True)
        self.assertEqual(Manager.refresh_calls, 0)

        with (
            mock.patch.object(
                MODULE.time,
                "monotonic",
                return_value=1000.0,
            ),
            mock.patch.object(
                MODULE,
                "_exclusive_auth_lock",
                wraps=MODULE._exclusive_auth_lock,
            ) as lock,
        ):
            self.assertFalse(Manager._hindsight_auth_available(manager))
            self.assertFalse(Manager._hindsight_auth_available(manager))
        self.assertEqual(lock.call_count, 1)
        self.assertEqual(lock.call_args.kwargs["timeout_seconds"], 0.0)

        auth_file.write_text("{invalid")
        auth_file.chmod(0o600)
        self.assertFalse(Manager._hindsight_auth_available(manager))

    def test_invalid_or_unreadable_auth_state_enters_sanitized_cooldown(
        self,
    ) -> None:
        for state in ("invalid", "missing"):
            with self.subTest(state=state):
                auth_file = self.root / state / "auth.json"
                auth_file.parent.mkdir(mode=0o700)
                if state == "invalid":
                    auth_file.write_text("{not-json")
                    auth_file.chmod(0o600)

                class TerminalRefreshError(RuntimeError):
                    pass

                class Manager:
                    refresh_calls = 0

                    def __init__(self) -> None:
                        self.access_token = "memory-access"
                        self.refresh_token = "memory-refresh"
                        self.account_id = ""
                        self._auth_file = auth_file

                    def refresh_tokens(self, reason="", *, force=False):
                        del reason, force
                        type(self).refresh_calls += 1

                    def _token_is_stale(self, skew_seconds=60):
                        del skew_seconds
                        return True

                manager_module = types.ModuleType(
                    "hindsight_api.engine.providers.codex_auth"
                )
                manager_module.CodexAuthManager = Manager
                manager_module.CodexRefreshExpiredError = (
                    TerminalRefreshError
                )
                MODULE._install_codex_auth_runtime(
                    manager_module,
                    cooldown_seconds=300,
                )
                manager = Manager()

                with self.assertRaisesRegex(
                    TerminalRefreshError,
                    "OAuth home is invalid or unreadable",
                ) as raised:
                    manager.refresh_tokens(reason="reactive", force=True)
                self.assertTrue(raised.exception.__suppress_context__)
                self.assertIsNone(raised.exception.__cause__)
                self.assertNotIn(str(auth_file), str(raised.exception))
                self.assertNotIn("{not-json", str(raised.exception))

                auth_file.write_text(
                    json.dumps(
                        {
                            "auth_mode": "chatgpt",
                            "tokens": {
                                "access_token": "memory-access",
                                "refresh_token": "memory-refresh",
                            },
                        }
                    )
                )
                auth_file.chmod(0o600)
                with self.assertRaisesRegex(
                    TerminalRefreshError,
                    "temporarily unavailable after terminal "
                    "authentication failure",
                ):
                    manager.refresh_tokens(reason="reactive", force=True)
                self.assertEqual(Manager.refresh_calls, 0)

    def test_auth_lock_oserror_enters_sanitized_terminal_cooldown(self) -> None:
        auth_file = self.root / "codex-lock-error" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": "memory-access",
                        "refresh_token": "memory-refresh",
                    },
                }
            )
        )
        auth_file.chmod(0o600)

        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            refresh_calls = 0

            def __init__(self) -> None:
                self.access_token = "memory-access"
                self.refresh_token = "memory-refresh"
                self.account_id = ""
                self._auth_file = auth_file

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force
                type(self).refresh_calls += 1

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError
        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )
        manager = Manager()

        with mock.patch.object(
            MODULE,
            "_exclusive_auth_lock",
            side_effect=OSError("sensitive lock failure"),
        ):
            with self.assertRaisesRegex(
                TerminalRefreshError,
                "OAuth home is invalid or unreadable",
            ) as raised:
                manager.refresh_tokens(reason="reactive", force=True)
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn("sensitive", str(raised.exception))

        with self.assertRaisesRegex(
            TerminalRefreshError,
            "temporarily unavailable after terminal authentication failure",
        ):
            manager.refresh_tokens(reason="reactive", force=True)
        self.assertEqual(Manager.refresh_calls, 0)

        with mock.patch.object(
            MODULE,
            "_exclusive_auth_lock",
            side_effect=OSError("sensitive availability failure"),
        ):
            self.assertFalse(Manager._hindsight_auth_available(manager))

    def test_relative_auth_path_is_rejected_with_sanitized_error(self) -> None:
        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            def __init__(self) -> None:
                self.access_token = "memory-access"
                self.refresh_token = "memory-refresh"
                self.account_id = ""
                self._auth_file = Path("relative/auth.json")

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError
        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )

        with self.assertRaisesRegex(
            TerminalRefreshError,
            "OAuth home is invalid or unreadable",
        ) as raised:
            manager = Manager()
            manager.refresh_tokens(reason="reactive", force=True)
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn("relative", str(raised.exception))
        self.assertFalse(Manager._hindsight_auth_available(manager))

    def test_duplicate_manager_closes_when_disk_adoption_fails(self) -> None:
        auth_file = self.root / "codex-canonical" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": "memory-access",
                        "refresh_token": "memory-refresh",
                    },
                }
            )
        )
        auth_file.chmod(0o600)

        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            fail_close = False

            def __init__(self) -> None:
                self.access_token = "memory-access"
                self.refresh_token = "memory-refresh"
                self.account_id = ""
                self._auth_file = auth_file
                self.closed = False

            def close(self) -> None:
                self.closed = True
                if self.fail_close:
                    raise RuntimeError("duplicate close failed")

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError
        canonicalize = MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )
        existing = Manager()
        duplicate = Manager()
        self.assertIs(canonicalize(existing), existing)

        auth_file.write_text("{invalid")
        auth_file.chmod(0o600)
        duplicate.fail_close = True
        self.assertIs(canonicalize(duplicate), existing)
        self.assertTrue(duplicate.closed)

    def test_auth_lock_timeout_does_not_enter_terminal_cooldown(self) -> None:
        auth_file = self.root / "codex-lock-timeout" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": "memory-access",
                        "refresh_token": "memory-refresh",
                    },
                }
            )
        )
        auth_file.chmod(0o600)

        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            refresh_calls = 0

            def __init__(self) -> None:
                self.access_token = "memory-access"
                self.refresh_token = "memory-refresh"
                self.account_id = ""
                self._auth_file = auth_file

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force
                type(self).refresh_calls += 1

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError
        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )
        manager = Manager()

        with mock.patch.object(
            MODULE,
            "_exclusive_auth_lock",
            side_effect=MODULE._AuthLockTimeout(
                "Timed out acquiring Hindsight Codex auth lock"
            ),
        ):
            for _ in range(2):
                with self.assertRaisesRegex(
                    MODULE._AuthLockTimeout,
                    "Timed out acquiring",
                ):
                    manager.refresh_tokens(reason="reactive", force=True)
        self.assertEqual(Manager.refresh_calls, 0)

    def test_nonterminal_refresh_error_does_not_enter_auth_cooldown(
        self,
    ) -> None:
        auth_file = self.root / "codex-network-error" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": "memory-access",
                        "refresh_token": "memory-refresh",
                    },
                }
            )
        )
        auth_file.chmod(0o600)

        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            refresh_calls = 0

            def __init__(self) -> None:
                self.access_token = "memory-access"
                self.refresh_token = "memory-refresh"
                self.account_id = ""
                self._auth_file = auth_file

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force
                type(self).refresh_calls += 1
                raise RuntimeError("transient provider failure")

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError
        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )
        manager = Manager()

        for _ in range(2):
            with self.assertRaisesRegex(
                RuntimeError,
                "transient provider failure",
            ):
                manager.refresh_tokens(reason="reactive", force=True)
        self.assertEqual(Manager.refresh_calls, 2)

    def test_codex_refresh_is_reactive_only(self) -> None:
        class TerminalRefreshError(RuntimeError):
            pass

        class Manager:
            def refresh_tokens(self, reason="", *, force=False):
                del reason, force

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.ModuleType(
            "hindsight_api.engine.providers.codex_auth"
        )
        manager_module.CodexAuthManager = Manager
        manager_module.CodexRefreshExpiredError = TerminalRefreshError

        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )

        self.assertFalse(Manager()._token_is_stale())
        self.assertTrue(
            Manager._hindsight_original_token_is_stale(Manager())
        )

    def test_arbitrary_codex_403_does_not_force_token_rotation(self) -> None:
        class Response:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self._payload = payload
                self.headers = {}

            def json(self):
                return self._payload

        class StatusError(RuntimeError):
            def __init__(self, response):
                self.response = response

        class CodexLLM:
            refresh_calls = 0

            async def _refresh_oauth_tokens(
                self,
                reason="",
                *,
                force=False,
            ):
                del reason, force
                type(self).refresh_calls += 1

        MODULE._install_definitive_codex_refresh(CodexLLM)
        provider = CodexLLM()

        async def refresh_while_handling(response):
            try:
                raise StatusError(response)
            except StatusError:
                await provider._refresh_oauth_tokens(
                    reason="provider wording is deliberately irrelevant",
                    force=True,
                )

        with self.assertRaisesRegex(
            RuntimeError,
            "not a definitive token failure",
        ):
            asyncio.run(
                refresh_while_handling(Response(403, {"error": "forbidden"}))
            )

        self.assertEqual(CodexLLM.refresh_calls, 0)
        asyncio.run(
            refresh_while_handling(Response(401))
        )
        self.assertEqual(CodexLLM.refresh_calls, 1)

        asyncio.run(
            refresh_while_handling(
                Response(403, {"error": {"code": "invalid_token"}})
            )
        )
        self.assertEqual(CodexLLM.refresh_calls, 2)

        with self.assertRaisesRegex(RuntimeError, "not a definitive"):
            asyncio.run(
                provider._refresh_oauth_tokens(
                    reason="speculative",
                    force=True,
                )
            )
        with self.assertRaisesRegex(RuntimeError, "not a definitive"):
            asyncio.run(
                provider._refresh_oauth_tokens(
                    reason="proactive",
                    force=False,
                )
            )
        with self.assertRaises(TypeError):
            asyncio.run(
                provider._refresh_oauth_tokens(
                    reason="controlled refresh canary",
                    force=True,
                    controlled_canary=True,
                )
            )
        self.assertEqual(CodexLLM.refresh_calls, 2)

    def test_controlled_canary_is_forwarded_when_delegate_supports_it(
        self,
    ) -> None:
        class CodexLLM:
            refresh_calls = []

            async def _refresh_oauth_tokens(
                self,
                reason="",
                *,
                force=False,
                controlled_canary=False,
            ):
                type(self).refresh_calls.append(
                    (reason, force, controlled_canary)
                )

        MODULE._install_definitive_codex_refresh(CodexLLM)
        provider = CodexLLM()
        asyncio.run(
            provider._refresh_oauth_tokens(
                reason="controlled refresh canary",
                force=True,
                controlled_canary=True,
            )
        )
        self.assertEqual(
            CodexLLM.refresh_calls,
            [("controlled refresh canary", True, True)],
        )

    def test_direct_response_status_controls_reactive_refresh(self) -> None:
        class Response:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self.payload = payload
                self.headers = {}

            def json(self):
                return self.payload

        class Client:
            def __init__(self, response):
                self.response = response

            async def post(self):
                return self.response

        class CodexLLM:
            refresh_calls = 0

            def __init__(self, response):
                self._client = Client(response)

            async def _refresh_oauth_tokens(
                self,
                reason="",
                *,
                force=False,
            ):
                del reason, force
                type(self).refresh_calls += 1

            async def call_with_tools(self):
                response = await self._client.post()
                if response.status_code in (401, 403):
                    await self._refresh_oauth_tokens(
                        reason="reactive direct response",
                        force=True,
                    )

        MODULE._install_definitive_codex_refresh(CodexLLM)
        asyncio.run(CodexLLM(Response(401)).call_with_tools())
        asyncio.run(
            CodexLLM(
                Response(403, {"error": {"code": "invalid_token"}})
            ).call_with_tools()
        )
        with self.assertRaisesRegex(RuntimeError, "not a definitive"):
            asyncio.run(
                CodexLLM(
                    Response(403, {"error": "forbidden"})
                ).call_with_tools()
            )
        successful_provider = CodexLLM(Response(200))

        async def refresh_after_success():
            await successful_provider._client.post()
            await successful_provider._refresh_oauth_tokens(
                reason="speculative after success",
                force=True,
            )

        with self.assertRaisesRegex(RuntimeError, "not a definitive"):
            asyncio.run(refresh_after_success())
        tracked_provider = CodexLLM(Response(200))
        tracked_provider._client.timeout_marker = "forwarded"
        self.assertEqual(
            tracked_provider._client._delegate.timeout_marker,
            "forwarded",
        )

        self.assertEqual(CodexLLM.refresh_calls, 2)

    def test_invalid_token_authenticate_header_is_definitive(self) -> None:
        class Response:
            status_code = 403
            headers = {"WWW-Authenticate": 'Bearer error="invalid_token"'}

            def json(self):
                return {}

        for value in (
            'Bearer error="invalid_token"',
            "Bearer error = invalid_token",
        ):
            with self.subTest(value=value):
                Response.headers = {"WWW-Authenticate": value}
                self.assertTrue(
                    MODULE._response_has_invalid_token(Response())
                )
        Response.headers = {
            "WWW-Authenticate": "Bearer error=invalid_tokenized"
        }
        self.assertFalse(MODULE._response_has_invalid_token(Response()))

    def test_deep_auth_error_payload_is_not_definitive(self) -> None:
        payload = {}
        cursor = payload
        for _ in range(2000):
            child = {}
            cursor["nested"] = child
            cursor = child
        cursor["code"] = "invalid_token"

        class Response:
            headers = {}

            def json(self):
                return payload

        self.assertFalse(MODULE._response_has_invalid_token(Response()))

    def test_terminal_auth_cooldown_skips_codex_outbound_call(self) -> None:
        class TerminalRefreshError(RuntimeError):
            pass

        class ManagerType:
            @staticmethod
            def _hindsight_auth_available(_manager):
                return False

        class CodexLLM:
            calls = 0

            def __init__(self):
                self._auth_manager = object()

            async def call(self, **kwargs):
                del kwargs
                type(self).calls += 1
                return "unexpected"

            async def call_with_tools(self, **kwargs):
                del kwargs
                type(self).calls += 1
                return "unexpected"

        MODULE._install_codex_circuit_breaker(
            CodexLLM,
            ManagerType,
            TerminalRefreshError,
        )
        provider = CodexLLM()

        for method in (provider.call, provider.call_with_tools):
            with self.assertRaisesRegex(
                TerminalRefreshError,
                "temporarily unavailable",
            ):
                asyncio.run(method())
        self.assertEqual(CodexLLM.calls, 0)

    def test_circuit_breaker_wires_only_supported_methods(self) -> None:
        class TerminalRefreshError(RuntimeError):
            pass

        class ManagerType:
            @staticmethod
            def _hindsight_auth_available(_manager):
                return True

        class CodexLLM:
            def __init__(self):
                self._auth_manager = object()

            async def call(self):
                return "ok"

        MODULE._install_codex_circuit_breaker(
            CodexLLM,
            ManagerType,
            TerminalRefreshError,
        )

        self.assertEqual(asyncio.run(CodexLLM().call()), "ok")
        self.assertFalse(hasattr(CodexLLM, "call_with_tools"))

    def test_embeddings_use_explicit_member_order(self) -> None:
        homes = {
            "home-relative:.fixture/primary": self.root / "primary",
            "home-relative:.fixture/secondary": self.root / "secondary",
        }
        for home in homes.values():
            home.mkdir(mode=0o700)
            auth_file = home / "auth.json"
            auth_file.write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": {"access_token": home.name},
                    }
                )
            )
            auth_file.chmod(0o600)

        class Embeddings:
            pass

        class CodexOAuthEmbeddings:
            instances = []
            fail_initialize = False

            def __init__(self, marker, **kwargs):
                self.marker = marker
                auth_file = MODULE._CODEX_AUTH_FILE_CONTEXT.get()
                self.home = str(auth_file.parent)
                self.kwargs = kwargs
                self._auth_manager = types.SimpleNamespace(
                    _auth_file=auth_file
                )
                self._dimension = 1536
                type(self).instances.append(self)

            async def initialize(self):
                if type(self).fail_initialize:
                    raise RuntimeError("readiness failed")
                return None

            def encode(self, texts):
                if self.home == str(homes["home-relative:.fixture/primary"]):
                    raise RuntimeError("primary unavailable")
                return [[float(len(text))] for text in texts]

            @property
            def dimension(self):
                return self._dimension

        embeddings_module = types.ModuleType("hindsight_api.engine.embeddings")
        embeddings_module.Embeddings = Embeddings
        embeddings_module.CodexOAuthEmbeddings = CodexOAuthEmbeddings
        policy = types.SimpleNamespace(
            failover_order=("member-primary", "member-secondary", "member-fallback"),
            embedding_failover_order=("member-primary", "member-secondary"),
            member=lambda member_id: {
                "member-primary": types.SimpleNamespace(
                    id="member-primary",
                    credential_mode="oauth-home",
                    credential_locator="home-relative:.fixture/primary",
                ),
                "member-secondary": types.SimpleNamespace(
                    id="member-secondary",
                    credential_mode="oauth-home",
                    credential_locator="home-relative:.fixture/secondary",
                ),
                "member-fallback": types.SimpleNamespace(
                    id="member-fallback",
                    credential_mode="none",
                    credential_locator=None,
                ),
            }[member_id],
        )

        MODULE._install_codex_embeddings_runtime(
            embeddings_module,
            policy,
            lambda locator: str(homes[locator]),
            ("member-primary", "member-secondary"),
        )
        wrapper = embeddings_module.CodexOAuthEmbeddings(
            "environment-positional",
            model="text-embedding-3-small",
        )
        asyncio.run(wrapper.initialize())
        asyncio.run(wrapper.initialize())

        self.assertEqual(
            [instance.home for instance in CodexOAuthEmbeddings.instances],
            [str(homes["home-relative:.fixture/primary"]), str(homes["home-relative:.fixture/secondary"])],
        )
        self.assertEqual(
            [instance.marker for instance in CodexOAuthEmbeddings.instances],
            ["environment-positional", "environment-positional"],
        )
        self.assertEqual(wrapper.encode(["one", "three"]), [[3.0], [5.0]])
        self.assertEqual(wrapper.dimension, 1536)
        self.assertEqual(len(wrapper._ready), 2)

        class CooldownManager:
            @staticmethod
            def _hindsight_auth_available(_manager):
                return False

        wrapper._ready[1][1]._auth_manager = CooldownManager()
        with self.assertRaisesRegex(RuntimeError, "primary unavailable"):
            wrapper.encode(["one"])

        wrapper._members[1][1]._dimension = 3072
        asyncio.run(wrapper.initialize())
        self.assertEqual(len(wrapper._ready), 1)
        self.assertEqual(wrapper.dimension, 1536)

        CodexOAuthEmbeddings.fail_initialize = True
        with self.assertRaisesRegex(RuntimeError, "All managed"):
            asyncio.run(wrapper.initialize())
        self.assertEqual(len(wrapper._ready), 1)
        self.assertEqual(wrapper.dimension, 1536)

    def test_embeddings_pass_supported_explicit_codex_home(self) -> None:
        primary_home = self.root / "primary"
        primary_home.mkdir(mode=0o700)

        class Embeddings:
            pass

        class CodexOAuthEmbeddings:
            def __init__(self, marker, *, codex_home=None, **kwargs):
                self.marker = marker
                self.home = codex_home
                self.kwargs = kwargs
                self._auth_manager = types.SimpleNamespace(
                    _auth_file=Path(codex_home) / "auth.json"
                )
                self._dimension = 1536

            async def initialize(self):
                return None

            @property
            def dimension(self):
                return self._dimension

            def encode(self, texts):
                return [[1.0] for _text in texts]

        embeddings_module = types.ModuleType("hindsight_api.engine.embeddings")
        embeddings_module.Embeddings = Embeddings
        embeddings_module.CodexOAuthEmbeddings = CodexOAuthEmbeddings
        member = types.SimpleNamespace(
            id="member-primary",
            credential_mode="oauth-home",
            credential_locator="home-relative:.fixture/primary",
        )
        policy = types.SimpleNamespace(
            failover_order=("member-primary",),
            embedding_failover_order=("member-primary",),
            member=lambda _member_id: member,
        )

        MODULE._install_codex_embeddings_runtime(
            embeddings_module,
            policy,
            lambda _locator: str(primary_home),
            ("member-primary",),
        )
        wrapper = embeddings_module.CodexOAuthEmbeddings(
            "explicit-positional",
            model="embedding",
        )

        self.assertEqual(wrapper._members[0][1].home, str(primary_home))
        self.assertEqual(
            wrapper._members[0][1].marker,
            "explicit-positional",
        )

    def test_embeddings_retry_only_definitive_auth_failures(self) -> None:
        homes = {
            "home-relative:.fixture/primary": self.root / "retry-primary",
            "home-relative:.fixture/secondary": self.root / "retry-secondary",
        }
        for home in homes.values():
            home.mkdir(mode=0o700)

        class Response:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self.payload = payload
                self.headers = {}

            def json(self):
                return self.payload

        class StatusError(RuntimeError):
            def __init__(self, response):
                self.response = response

        for (
            label,
            response,
            refresh_changes_token,
            expected_refreshes,
            expected_value,
        ) in (
            ("401", Response(401), True, 1, 11.0),
            (
                "invalid-403",
                Response(403, {"error": {"code": "invalid_token"}}),
                True,
                1,
                11.0,
            ),
            (
                "arbitrary-403",
                Response(403, {"error": "forbidden"}),
                True,
                0,
                22.0,
            ),
            ("unchanged-after-refresh", Response(401), False, 1, 22.0),
        ):
            with self.subTest(label=label):
                class Embeddings:
                    pass

                class Manager:
                    refresh_calls = 0

                    def __init__(self, auth_file):
                        self._auth_file = auth_file
                        self.access_token = "before"

                    @staticmethod
                    def _hindsight_auth_available(_manager):
                        return True

                    def refresh_tokens(self, reason="", *, force=False):
                        del reason, force
                        type(self).refresh_calls += 1
                        if refresh_changes_token:
                            self.access_token = "after"

                class Client:
                    api_key = "before"

                class CodexOAuthEmbeddings:
                    def __init__(self, *, codex_home=None):
                        self.home = Path(codex_home)
                        self._auth_manager = Manager(
                            self.home / "auth.json"
                        )
                        self.api_key = "before"
                        self._client = Client()
                        self.calls = 0
                        self._dimension = 1536

                    async def initialize(self):
                        return None

                    @property
                    def dimension(self):
                        return self._dimension

                    def encode(self, texts):
                        del texts
                        self.calls += 1
                        if (
                            self.home == homes["home-relative:.fixture/primary"]
                            and self.calls == 1
                        ):
                            raise StatusError(response)
                        value = (
                            11.0
                            if self.home == homes["home-relative:.fixture/primary"]
                            else 22.0
                        )
                        return [[value]]

                embeddings_module = types.ModuleType(
                    "hindsight_api.engine.embeddings"
                )
                embeddings_module.Embeddings = Embeddings
                embeddings_module.CodexOAuthEmbeddings = (
                    CodexOAuthEmbeddings
                )
                members = {
                    member_id: types.SimpleNamespace(
                        id=member_id,
                        credential_mode="oauth-home",
                        credential_locator=locator,
                    )
                    for member_id, locator in (
                        ("member-primary", "home-relative:.fixture/primary"),
                        ("member-secondary", "home-relative:.fixture/secondary"),
                    )
                }
                policy = types.SimpleNamespace(
                    failover_order=("member-primary", "member-secondary"),
                    embedding_failover_order=(
                        "member-primary",
                        "member-secondary",
                    ),
                    member=members.__getitem__,
                )
                MODULE._install_codex_embeddings_runtime(
                    embeddings_module,
                    policy,
                    lambda locator: str(homes[locator]),
                    ("member-primary", "member-secondary"),
                )
                wrapper = embeddings_module.CodexOAuthEmbeddings()
                asyncio.run(wrapper.initialize())

                self.assertEqual(
                    wrapper.encode(["memory"]),
                    [[expected_value]],
                )
                primary = wrapper._members[0][1]
                self.assertEqual(
                    primary._auth_manager.refresh_calls,
                    expected_refreshes,
                )
                self.assertEqual(
                    primary.calls,
                    (
                        2
                        if refresh_changes_token and expected_refreshes
                        else 1
                    ),
                )


if __name__ == "__main__":
    unittest.main()
