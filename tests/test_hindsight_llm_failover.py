from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = (
    REPO_ROOT
    / "home/private_dot_local/lib/hindsight-runtime/hindsight_llm_failover.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("hindsight_llm_failover", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    status_code = 429

    def __init__(self, resets_at: float) -> None:
        self._resets_at = resets_at

    def json(self):
        return {
            "error": {
                "type": "usage_limit_reached",
                "resets_at": self._resets_at,
            }
        }


class UsageLimitError(Exception):
    def __init__(self, resets_at: float) -> None:
        self.response = FakeResponse(resets_at)


class Member:
    provider = "openai-codex"
    model = "gpt-5.3-codex-spark"

    def __init__(self, api_key: str, outcomes: list[object]) -> None:
        self.api_key = api_key
        self.outcomes = outcomes
        self.calls = 0

    async def call(self, **_kwargs):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class HindsightLLMFailoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_codex_home_marker_is_scoped_and_restored(self) -> None:
        prior = "/tmp/original-codex-home"
        with mock.patch.dict(os.environ, {"CODEX_HOME": prior}, clear=False):
            with self.module.codex_home_environment("codex-home:/tmp/work-codex-home"):
                self.assertEqual(os.environ["CODEX_HOME"], "/tmp/work-codex-home")
            self.assertEqual(os.environ["CODEX_HOME"], prior)

    def test_usage_limit_reset_is_extracted_without_a_probe(self) -> None:
        self.assertEqual(
            self.module.usage_limit_reset_at(UsageLimitError(1234.0), now=1000.0),
            1234.0,
        )

    def test_dispatch_skips_quota_limited_account_until_reset(self) -> None:
        now = [1000.0]
        dispatcher = self.module.QuotaAwareDispatcher(clock=lambda: now[0])
        work = Member("codex-home:/work", [UsageLimitError(1100.0), "work recovered"])
        personal = Member("codex-home:/personal", ["personal", "personal again"])

        first = asyncio.run(
            dispatcher.dispatch(
                [work, personal],
                [0, 1],
                "call",
                {},
                lambda exc: isinstance(exc, Exception),
            )
        )
        second = asyncio.run(
            dispatcher.dispatch(
                [work, personal],
                [0, 1],
                "call",
                {},
                lambda exc: isinstance(exc, Exception),
            )
        )
        now[0] = 1101.0
        third = asyncio.run(
            dispatcher.dispatch(
                [work, personal],
                [0, 1],
                "call",
                {},
                lambda exc: isinstance(exc, Exception),
            )
        )

        self.assertEqual((first, second, third), ("personal", "personal again", "work recovered"))
        self.assertEqual(work.calls, 2)
        self.assertEqual(personal.calls, 2)

    def test_hatchery_guard_overrides_only_hatchery_member_settings(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.timeout = 120

            def with_options(self, *, timeout: int):
                clone = Client()
                clone.timeout = timeout
                return clone

        class ProviderImpl:
            def __init__(self) -> None:
                self.timeout = 120
                self._client = Client()

        class Provider:
            def __init__(self, provider: str, model: str, base_url: str) -> None:
                self.provider = provider
                self.model = model
                self.base_url = base_url
                self.timeout = 120
                self.max_retries = 3
                self._provider_impl = ProviderImpl()

        hatchery = Provider(
            "lmstudio",
            "Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL",
            "http://hatchery.komodo-vector.ts.net:13305/v1",
        )
        codex = Provider("openai-codex", "gpt-5.3-codex-spark", "")
        guard = self.module.HatcheryGuard()

        guard.prepare(hatchery)
        guard.prepare(codex)

        self.assertEqual(hatchery.timeout, 300)
        self.assertEqual(hatchery.max_retries, 0)
        self.assertEqual(hatchery._provider_impl.timeout, 300)
        self.assertEqual(hatchery._provider_impl._client.timeout, 300)
        self.assertEqual(codex.timeout, 120)
        self.assertEqual(codex.max_retries, 3)
        self.assertEqual(codex._provider_impl.timeout, 120)
        self.assertEqual(codex._provider_impl._client.timeout, 120)

    def test_hatchery_guard_serializes_hatchery_without_blocking_codex(self) -> None:
        class Provider:
            def __init__(self, provider: str, model: str, base_url: str) -> None:
                self.provider = provider
                self.model = model
                self.base_url = base_url
                self.timeout = 120
                self.max_retries = 3
                self._provider_impl = None

        hatchery = Provider(
            "lmstudio",
            "Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL",
            "http://hatchery.komodo-vector.ts.net:13305/v1",
        )
        codex = Provider("openai-codex", "gpt-5.3-codex-spark", "")

        async def scenario() -> None:
            guard = self.module.HatcheryGuard()
            first_started = asyncio.Event()
            second_started = asyncio.Event()
            release_first = asyncio.Event()
            codex_completed = asyncio.Event()
            hatchery_active = 0
            hatchery_max_active = 0

            async def operation(label: str, member: Provider, **kwargs):
                nonlocal hatchery_active, hatchery_max_active
                if member is codex:
                    codex_completed.set()
                    return kwargs
                hatchery_active += 1
                hatchery_max_active = max(hatchery_max_active, hatchery_active)
                try:
                    if label == "first":
                        first_started.set()
                        await release_first.wait()
                    else:
                        second_started.set()
                    return kwargs
                finally:
                    hatchery_active -= 1

            first = asyncio.create_task(
                guard.call(hatchery, operation, "first", hatchery, max_retries=7)
            )
            await first_started.wait()
            second = asyncio.create_task(
                guard.call(hatchery, operation, "second", hatchery, max_retries=7)
            )
            codex_call = asyncio.create_task(
                guard.call(codex, operation, "codex", codex, max_retries=7)
            )
            await codex_completed.wait()

            self.assertFalse(second_started.is_set())
            release_first.set()
            first_result, second_result, codex_result = await asyncio.gather(
                first,
                second,
                codex_call,
            )

            self.assertEqual(hatchery_max_active, 1)
            self.assertEqual(first_result["max_retries"], 0)
            self.assertEqual(second_result["max_retries"], 0)
            self.assertEqual(codex_result["max_retries"], 7)

        asyncio.run(scenario())

    def test_install_patches_direct_hatchery_provider_without_touching_codex(self) -> None:
        class Client:
            def __init__(self, timeout: int) -> None:
                self.timeout = timeout

            def with_options(self, *, timeout: int):
                return Client(timeout)

        class ProviderImpl:
            def __init__(self, timeout: int) -> None:
                self.timeout = timeout
                self._client = Client(timeout)

        class LLMProvider:
            def __init__(
                self,
                provider: str,
                api_key: str,
                base_url: str,
                model: str,
                reasoning_effort: str = "low",
                timeout: int = 120,
                max_retries: int = 3,
                **_kwargs,
            ) -> None:
                self.provider = provider
                self.api_key = api_key
                self.base_url = base_url
                self.model = model
                self.reasoning_effort = reasoning_effort
                self.timeout = timeout
                self.max_retries = max_retries
                self._provider_impl = ProviderImpl(timeout)

            async def call(self, **kwargs):
                return kwargs

            async def call_with_tools(self, **kwargs):
                return kwargs

        class CodexLLM:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class MultiLLMProvider:
            async def _dispatch(self, _method_name: str, **_kwargs):
                return None

        multi_module = types.ModuleType("hindsight_api.engine.multi_llm")
        multi_module.MultiLLMProvider = MultiLLMProvider
        multi_module._should_failover = lambda exc: isinstance(exc, Exception)
        multi_module.logger = logging.getLogger("test-hindsight-failover")
        codex_module = types.ModuleType("hindsight_api.engine.providers.codex_llm")
        codex_module.CodexLLM = CodexLLM
        wrapper_module = types.ModuleType("hindsight_api.engine.llm_wrapper")
        wrapper_module.LLMProvider = LLMProvider

        with mock.patch.dict(
            sys.modules,
            {
                "hindsight_api.engine.multi_llm": multi_module,
                "hindsight_api.engine.providers.codex_llm": codex_module,
                "hindsight_api.engine.llm_wrapper": wrapper_module,
            },
        ):
            self.assertTrue(self.module.install_hindsight_patches())

        hatchery = LLMProvider(
            provider="lmstudio",
            api_key="",
            base_url="http://hatchery.komodo-vector.ts.net:13305/v1",
            model="Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL",
        )
        codex = LLMProvider(
            provider="openai-codex",
            api_key="codex-home:/work",
            base_url="",
            model="gpt-5.3-codex-spark",
        )

        hatchery_result = asyncio.run(hatchery.call(max_retries=7))
        codex_result = asyncio.run(codex.call(max_retries=7))

        self.assertEqual(hatchery.timeout, 300)
        self.assertEqual(hatchery._provider_impl._client.timeout, 300)
        self.assertEqual(hatchery_result["max_retries"], 0)
        self.assertEqual(codex.timeout, 120)
        self.assertEqual(codex._provider_impl._client.timeout, 120)
        self.assertEqual(codex_result["max_retries"], 7)


if __name__ == "__main__":
    unittest.main()
