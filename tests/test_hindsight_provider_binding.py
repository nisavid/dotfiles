from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SOURCE_TEMPLATE = (
    ROOT
    / "home/private_dot_local/lib/hindsight-runtime/sitecustomize.py.tmpl"
)
FIXTURE = ROOT / "tests/fixtures/hindsight-public.toml"
_SOURCE_PHASE = tempfile.TemporaryDirectory()
SOURCE = Path(_SOURCE_PHASE.name) / "sitecustomize.py"
with SOURCE.open("x", encoding="utf-8") as rendered_source:
    subprocess.run(
        [
            "chezmoi",
            "-S",
            str(ROOT / "home"),
            "--override-data-file",
            str(FIXTURE),
            "execute-template",
        ],
        check=True,
        input=SOURCE_TEMPLATE.read_text(encoding="utf-8"),
        stdout=rendered_source,
        text=True,
    )
SPEC = importlib.util.spec_from_file_location("hindsight_sitecustomize", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@unittest.skipUnless(
    sys.platform == "darwin",
    "the current Hindsight provider binding is Darwin-only",
)
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

    def test_policy_path_ignores_environment_override(self) -> None:
        previous = os.environ.get("HINDSIGHT_PROVIDER_POLICY_PATH")
        os.environ["HINDSIGHT_PROVIDER_POLICY_PATH"] = str(
            self.root / "untrusted-policy.json"
        )
        try:
            self.assertEqual(
                MODULE._provider_policy_path(self.root),
                self.root / ".fixture/config/provider-policy.json",
            )
        finally:
            if previous is None:
                os.environ.pop("HINDSIGHT_PROVIDER_POLICY_PATH", None)
            else:
                os.environ["HINDSIGHT_PROVIDER_POLICY_PATH"] = previous

    def test_declares_four_independent_oauth_homes(self) -> None:
        self.assertEqual(
            MODULE._oauth_homes(self.root),
            {
                "oauth-home:work": self.root / ".fixture/auth/work",
                "oauth-home:personal": self.root / ".fixture/auth/personal",
                "oauth-home:alt1": self.root / ".fixture/auth/alt1",
                "oauth-home:alt2": self.root / ".fixture/auth/alt2",
            },
        )

    def test_resolves_the_installer_owned_active_json_record(self) -> None:
        install_root = self.root / "install"
        install_root.mkdir(mode=0o700)
        releases = install_root / "releases"
        releases.mkdir(mode=0o700)
        digest = "a" * 64
        release = releases / f"2026.07.28+candidate-{digest[:16]}"
        release.mkdir(mode=0o700)
        active = install_root / "active.json"
        active.write_text(
            '{"version":"2026.07.28+candidate",'
            f'"release_digest":"{digest}",'
            f'"release_path":"releases/{release.name}"}}'
        )
        active.chmod(0o600)

        self.assertEqual(
            MODULE._resolve_active_release(install_root),
            release.resolve(),
        )
        self.assertFalse((install_root / "active").exists())
        invalid_records = {
            "duplicate-key": (
                '{"version":"2026.07.28+candidate",'
                f'"release_digest":"{digest}",'
                f'"release_digest":"{digest}",'
                f'"release_path":"releases/{release.name}"}}'
            ),
            "wrong-release": (
                '{"version":"2026.07.28+candidate",'
                f'"release_digest":"{digest}",'
                '"release_path":"releases/wrong"}'
            ),
        }
        for label, payload in invalid_records.items():
            with self.subTest(label=label):
                active.write_text(payload)
                active.chmod(0o600)
                with self.assertRaises(RuntimeError):
                    MODULE._resolve_active_release(install_root)
        active.write_text(
            '{"version":"2026.07.28+candidate",'
            f'"release_digest":"{digest}",'
            f'"release_path":"releases/{release.name}"}}'
        )
        active.chmod(0o600)
        outside = self.root / "outside-release"
        outside.mkdir(mode=0o700)
        release.rmdir()
        release.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "release path is invalid"):
            MODULE._resolve_active_release(install_root)

    def test_cross_process_auth_lock_times_out(self) -> None:
        auth_file = self.root / "codex" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        with mock.patch.object(
            MODULE.fcntl,
            "flock",
            side_effect=BlockingIOError,
        ):
            with self.assertRaisesRegex(RuntimeError, "Timed out acquiring"):
                with MODULE._exclusive_auth_lock(
                    auth_file,
                    timeout_seconds=0.0,
                ):
                    self.fail("lock should not have been acquired")

    def test_codex_manager_rereads_changed_login_file(self) -> None:
        auth_file = self.root / "codex-reread" / "auth.json"
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

        manager_module = types.SimpleNamespace(
            CodexAuthManager=Manager,
            CodexRefreshExpiredError=TerminalRefreshError,
        )
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

    def test_lock_timeout_adopts_another_process_refresh(self) -> None:
        auth_file = self.root / "codex-contention" / "auth.json"
        auth_file.parent.mkdir(mode=0o700)
        auth_file.write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": "fresh-access",
                        "refresh_token": "fresh-refresh",
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
                self.account_id = None
                self._auth_file = auth_file

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force
                type(self).refresh_calls += 1

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.SimpleNamespace(
            CodexAuthManager=Manager,
            CodexRefreshExpiredError=TerminalRefreshError,
        )
        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )
        manager = Manager()
        with mock.patch.object(
            MODULE,
            "_exclusive_auth_lock",
            side_effect=MODULE._AuthLockTimeout("contended"),
        ):
            manager.refresh_tokens(reason="reactive", force=True)

        self.assertEqual(Manager.refresh_calls, 0)
        self.assertEqual(manager.access_token, "fresh-access")
        self.assertEqual(manager.refresh_token, "fresh-refresh")

    def test_terminal_refresh_failure_enters_cooldown(self) -> None:
        auth_file = self.root / "codex-cooldown" / "auth.json"
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
                self.account_id = None
                self._auth_file = auth_file

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force
                type(self).refresh_calls += 1
                raise TerminalRefreshError("terminal")

            def _token_is_stale(self, skew_seconds=60):
                del skew_seconds
                return True

        manager_module = types.SimpleNamespace(
            CodexAuthManager=Manager,
            CodexRefreshExpiredError=TerminalRefreshError,
        )
        MODULE._install_codex_auth_runtime(
            manager_module,
            cooldown_seconds=300,
        )
        manager = Manager()
        with self.assertRaisesRegex(
            TerminalRefreshError,
            "terminally invalid",
        ):
            manager.refresh_tokens(reason="reactive", force=True)
        with self.assertRaisesRegex(
            TerminalRefreshError,
            "temporarily unavailable",
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
        self.assertTrue(Manager._hindsight_auth_available(manager))
        self.assertEqual(manager.access_token, "reauthorized-access")
        self.assertEqual(manager.refresh_token, "reauthorized-refresh")

    def test_arbitrary_403_does_not_rotate_codex_credentials(self) -> None:
        class Response:
            headers = {}

            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self.payload = payload

            def json(self):
                return self.payload

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
                    reason="reactive",
                    force=True,
                )

        with self.assertRaisesRegex(RuntimeError, "not a definitive"):
            asyncio.run(
                refresh_while_handling(
                    Response(403, {"error": "forbidden"})
                )
            )
        self.assertEqual(CodexLLM.refresh_calls, 0)

        asyncio.run(refresh_while_handling(Response(401)))
        asyncio.run(
            refresh_while_handling(
                Response(403, {"error": {"code": "invalid_token"}})
            )
        )
        self.assertEqual(CodexLLM.refresh_calls, 2)

    def test_wrapped_401_authorizes_reactive_refresh(self) -> None:
        class Response:
            status_code = 401
            headers = {}

            @staticmethod
            def json():
                return {}

        class StatusError(RuntimeError):
            def __init__(self):
                self.response = Response()

        class WrappedError(RuntimeError):
            pass

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

        async def refresh_while_handling():
            try:
                try:
                    raise StatusError()
                except StatusError as error:
                    raise WrappedError("wrapped") from error
            except WrappedError:
                await provider._refresh_oauth_tokens(
                    reason="reactive",
                    force=True,
                )

        asyncio.run(refresh_while_handling())
        self.assertEqual(CodexLLM.refresh_calls, 1)

    def test_refresh_client_preserves_exception_response(self) -> None:
        response = object()

        class StatusError(RuntimeError):
            def __init__(self):
                self.response = response

        class Client:
            @staticmethod
            def post(*_args, **_kwargs):
                raise StatusError()

        owner = types.SimpleNamespace()
        wrapper = MODULE._CodexRefreshTrackingClient(Client(), owner)
        with self.assertRaises(StatusError):
            wrapper.post("/oauth/token")
        self.assertIs(owner._hindsight_last_refresh_response, response)

    def test_controlled_refresh_canary_is_forwarded(self) -> None:
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
        asyncio.run(
            CodexLLM()._refresh_oauth_tokens(
                reason="controlled refresh canary",
                force=True,
                controlled_canary=True,
            )
        )
        self.assertEqual(
            CodexLLM.refresh_calls,
            [("controlled refresh canary", True, True)],
        )

    def test_terminal_auth_circuit_breaker_skips_outbound_call(self) -> None:
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

            async def call(self):
                type(self).calls += 1

            async def call_with_tools(self):
                type(self).calls += 1

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

    def test_embeddings_use_all_four_explicit_oauth_homes(self) -> None:
        homes = MODULE._oauth_homes(self.root)
        (self.root / ".hindsight").mkdir(mode=0o700)
        for home in homes.values():
            home.mkdir(parents=True, mode=0o700)
        home_values = {
            str(home): float(index)
            for index, home in enumerate(homes.values(), start=1)
        }

        class Embeddings:
            pass

        class Response:
            status_code = 401
            headers = {}

            @staticmethod
            def json():
                return {}

        class StatusError(RuntimeError):
            def __init__(self):
                self.response = Response()

        class Client:
            def __init__(self):
                self.api_key = "initial"

        class Manager:
            cooldown_homes = set()

            def __init__(self, home):
                self.home = home
                self._auth_file = Path(home) / "auth.json"
                self.access_token = "initial"
                self.refresh_calls = 0

            @staticmethod
            def _hindsight_auth_available(manager):
                return manager.home not in Manager.cooldown_homes

            def refresh_tokens(self, reason="", *, force=False):
                del reason, force
                self.refresh_calls += 1
                self.access_token = f"rotated:{self.home}"

        class CodexOAuthEmbeddings:
            instances = []

            def __init__(self, *, codex_home=None):
                self.home = codex_home
                self._auth_manager = Manager(codex_home)
                self.api_key = "initial"
                self._client = Client()
                self.calls = 0
                self._dimension = 1536
                type(self).instances.append(self)

            async def initialize(self):
                return None

            def encode(self, texts):
                self.calls += 1
                if (
                    self.home == str(homes["oauth-home:work"])
                    and self.calls == 1
                ):
                    raise StatusError()
                return [[home_values[self.home]] for _text in texts]

            @property
            def dimension(self):
                return self._dimension

        embeddings_module = types.SimpleNamespace(
            Embeddings=Embeddings,
            CodexOAuthEmbeddings=CodexOAuthEmbeddings,
        )
        member_specs = (
            ("work-codex", "oauth-home:work"),
            ("personal-codex", "oauth-home:personal"),
            ("alt1-codex", "oauth-home:alt1"),
            ("alt2-codex", "oauth-home:alt2"),
        )
        members = {
            member_id: types.SimpleNamespace(
                id=member_id,
                credential_mode="oauth-home",
                credential_locator=locator,
            )
            for member_id, locator in member_specs
        }
        order = tuple(member_id for member_id, _ in member_specs)
        policy = types.SimpleNamespace(member=members.__getitem__)

        MODULE._install_codex_embeddings_runtime(
            embeddings_module,
            policy,
            lambda locator: str(homes[locator]),
            order,
        )
        wrapper = embeddings_module.CodexOAuthEmbeddings()
        asyncio.run(wrapper.initialize())

        self.assertEqual(
            [instance.home for instance in CodexOAuthEmbeddings.instances],
            [str(homes[locator]) for _, locator in member_specs],
        )
        self.assertEqual(len(wrapper._ready), 4)
        self.assertEqual(wrapper.encode(["memory"]), [[1.0]])
        work = CodexOAuthEmbeddings.instances[0]
        self.assertEqual(work._auth_manager.refresh_calls, 1)
        self.assertEqual(work.api_key, f"rotated:{work.home}")
        self.assertEqual(work._client.api_key, f"rotated:{work.home}")

        Manager.cooldown_homes = {work.home}
        self.assertEqual(wrapper.encode(["memory"]), [[2.0]])
        Manager.cooldown_homes = set(home_values)
        with self.assertRaisesRegex(
            RuntimeError,
            "All remaining managed Codex embeddings members",
        ):
            wrapper.encode(["memory"])

    def test_resolves_and_caches_a_strict_protected_api_key_file(self) -> None:
        secret_parent = self.root / ".fixture" / "secrets"
        secret_parent.mkdir(parents=True, mode=0o700)
        secret_parent.parent.chmod(0o700)
        key_file = secret_parent / "hindsight-openai.env"
        key_file.write_text(
            "HINDSIGHT_OPENAI_API_KEY=sk-synthetic-first\n",
            encoding="utf-8",
        )
        key_file.chmod(0o600)
        mapping = {
            "api-key:hindsight-openai": (
                ".fixture/secrets/hindsight-openai.env"
            )
        }
        cache: dict[str, str] = {}

        first = MODULE._resolve_api_key(
            self.root,
            "api-key:hindsight-openai",
            mapping,
            cache,
        )
        key_file.write_text(
            "HINDSIGHT_OPENAI_API_KEY=sk-synthetic-second\n",
            encoding="utf-8",
        )
        second = MODULE._resolve_api_key(
            self.root,
            "api-key:hindsight-openai",
            mapping,
            cache,
        )

        self.assertEqual(first, "sk-synthetic-first")
        self.assertEqual(second, first)

    def test_api_key_file_parser_rejects_ambiguous_or_malformed_content(self) -> None:
        invalid_payloads = (
            b"",
            b"OPENAI_API_KEY=sk-wrong-name\n",
            b"HINDSIGHT_OPENAI_API_KEY=\n",
            b"HINDSIGHT_OPENAI_API_KEY=sk-first\nEXTRA=value\n",
            b"HINDSIGHT_OPENAI_API_KEY=sk has-space\n",
            b"HINDSIGHT_OPENAI_API_KEY=sk-first\r\n",
            b"\xff",
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaisesRegex(
                RuntimeError,
                "invalid",
            ):
                MODULE._parse_api_key_file(payload)

    def test_api_key_resolution_rejects_unknown_or_unprotected_locations(self) -> None:
        mapping = {
            "api-key:hindsight-openai": (
                ".fixture/secrets/hindsight-openai.env"
            )
        }
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            MODULE._resolve_api_key(
                self.root,
                "api-key:unknown",
                mapping,
                {},
            )

        secret_parent = self.root / ".fixture" / "secrets"
        secret_parent.mkdir(parents=True, mode=0o700)
        secret_parent.parent.chmod(0o700)
        key_file = secret_parent / "hindsight-openai.env"
        key_file.write_text(
            "HINDSIGHT_OPENAI_API_KEY=sk-synthetic\n",
            encoding="utf-8",
        )
        key_file.chmod(0o600)
        secret_parent.chmod(0o750)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._resolve_api_key(
                self.root,
                "api-key:hindsight-openai",
                mapping,
                {},
            )

    def test_embeddings_injection_accepts_only_the_managed_marker(self) -> None:
        marker = "provider-policy:openai-luna"
        resolver = mock.Mock(return_value="sk-synthetic")
        environment = {
            "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY": marker,
        }

        MODULE._inject_embeddings_api_key(
            environment,
            provider="openai",
            marker=marker,
            locator="api-key:hindsight-openai",
            resolver=resolver,
        )

        self.assertEqual(
            environment["HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY"],
            "sk-synthetic",
        )
        resolver.assert_called_once_with("api-key:hindsight-openai")

        with self.assertRaisesRegex(RuntimeError, "conflicts"):
            MODULE._inject_embeddings_api_key(
                {
                    "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY": (
                        "sk-unmanaged"
                    )
                },
                provider="openai",
                marker=marker,
                locator="api-key:hindsight-openai",
                resolver=resolver,
            )

        for unmanaged in (None, ""):
            with self.subTest(unmanaged=unmanaged):
                unmanaged_environment = {}
                if unmanaged is not None:
                    unmanaged_environment[
                        "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY"
                    ] = unmanaged
                unmanaged_resolver = mock.Mock(
                    return_value="sk-synthetic"
                )
                with self.assertRaisesRegex(RuntimeError, "conflicts"):
                    MODULE._inject_embeddings_api_key(
                        unmanaged_environment,
                        provider="openai",
                        marker=marker,
                        locator="api-key:hindsight-openai",
                        resolver=unmanaged_resolver,
                    )
                unmanaged_resolver.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
