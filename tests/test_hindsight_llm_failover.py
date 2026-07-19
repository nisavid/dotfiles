from __future__ import annotations

import asyncio
import importlib.util
import os
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


if __name__ == "__main__":
    unittest.main()
