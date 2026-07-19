from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


CODEX_HOME_MARKER = "codex-home:"
DEFAULT_USAGE_LIMIT_COOLDOWN_SECONDS = 300.0
HATCHERY_PROVIDER = "lmstudio"
HATCHERY_MODEL = "Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL"
HATCHERY_BASE_URL = "http://hatchery.komodo-vector.ts.net:13305/v1"
HATCHERY_MAX_CONCURRENT = 1
HATCHERY_MAX_RETRIES = 0
HATCHERY_TIMEOUT_SECONDS = 300
_CODEX_ENVIRONMENT_LOCK = threading.Lock()


def codex_home_marker(path: Path | str) -> str:
    home = Path(path).expanduser()
    if not home.is_absolute():
        raise ValueError("Codex home must be absolute")
    return f"{CODEX_HOME_MARKER}{home}"


def codex_home_from_api_key(api_key: str | None) -> Path | None:
    if not api_key or not api_key.startswith(CODEX_HOME_MARKER):
        return None
    value = api_key.removeprefix(CODEX_HOME_MARKER)
    home = Path(value).expanduser()
    if not value or not home.is_absolute():
        raise ValueError("Invalid Codex home marker")
    return home


@contextmanager
def codex_home_environment(api_key: str | None) -> Iterator[None]:
    home = codex_home_from_api_key(api_key)
    if home is None:
        yield
        return

    with _CODEX_ENVIRONMENT_LOCK:
        previous = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = str(home)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = previous


def _response_payload(exc: BaseException) -> tuple[int | None, dict[str, Any] | None]:
    response = getattr(exc, "response", None)
    if response is None:
        return None, None
    status = getattr(response, "status_code", None)
    try:
        payload = response.json()
    except Exception:
        try:
            payload = json.loads(response.text)
        except Exception:
            payload = None
    return status, payload if isinstance(payload, dict) else None


def usage_limit_reset_at(exc: BaseException, *, now: float | None = None) -> float | None:
    now = time.time() if now is None else now
    status, payload = _response_payload(exc)
    if status != 429 or payload is None:
        return None
    error = payload.get("error")
    if not isinstance(error, dict) or error.get("type") != "usage_limit_reached":
        return None

    reset = error.get("resets_at")
    if isinstance(reset, (int, float)) and reset > now:
        return float(reset)
    remaining = error.get("resets_in_seconds")
    if isinstance(remaining, (int, float)) and remaining > 0:
        return now + float(remaining)
    return now + DEFAULT_USAGE_LIMIT_COOLDOWN_SECONDS


class HatcheryGuard:
    def __init__(self) -> None:
        self._semaphore: asyncio.Semaphore | None = None
        self._semaphore_loop: asyncio.AbstractEventLoop | None = None

    def _current_semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._semaphore_loop is not loop:
            self._semaphore = asyncio.Semaphore(HATCHERY_MAX_CONCURRENT)
            self._semaphore_loop = loop
        return self._semaphore

    @staticmethod
    def applies_to(member: Any) -> bool:
        return (
            getattr(member, "provider", "").lower() == HATCHERY_PROVIDER
            and getattr(member, "model", "") == HATCHERY_MODEL
            and str(getattr(member, "base_url", "")).rstrip("/")
            == HATCHERY_BASE_URL.rstrip("/")
        )

    def prepare(self, member: Any) -> None:
        if not self.applies_to(member) or getattr(member, "_hindsight_hatchery_prepared", False):
            return

        member.timeout = HATCHERY_TIMEOUT_SECONDS
        member.max_retries = HATCHERY_MAX_RETRIES
        provider_impl = getattr(member, "_provider_impl", None)
        if provider_impl is not None:
            provider_impl.timeout = HATCHERY_TIMEOUT_SECONDS
            client = getattr(provider_impl, "_client", None)
            if client is not None and hasattr(client, "with_options"):
                provider_impl._client = client.with_options(timeout=HATCHERY_TIMEOUT_SECONDS)
        member._hindsight_hatchery_prepared = True

    async def call(
        self,
        member: Any,
        operation: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not self.applies_to(member):
            return await operation(*args, **kwargs)

        self.prepare(member)
        hatchery_kwargs = dict(kwargs)
        hatchery_kwargs["max_retries"] = HATCHERY_MAX_RETRIES
        async with self._current_semaphore():
            return await operation(*args, **hatchery_kwargs)


class QuotaAwareDispatcher:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        logger: logging.Logger | None = None,
    ) -> None:
        self._clock = clock
        self._logger = logger or logging.getLogger(__name__)
        self._cooldowns: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _member_key(member: Any) -> str | None:
        api_key = getattr(member, "api_key", None)
        home = codex_home_from_api_key(api_key)
        return str(home) if home is not None else None

    def _available(self, key: str | None, now: float) -> bool:
        if key is None:
            return True
        with self._lock:
            reset = self._cooldowns.get(key)
            if reset is None:
                return True
            if reset <= now:
                self._cooldowns.pop(key, None)
                return True
            return False

    def _cool_down(self, key: str, reset_at: float) -> None:
        with self._lock:
            self._cooldowns[key] = max(reset_at, self._cooldowns.get(key, 0.0))

    async def dispatch(
        self,
        members: list[Any],
        order: list[int],
        method_name: str,
        kwargs: dict[str, Any],
        should_failover: Callable[[BaseException], bool],
    ) -> Any:
        last_exc: BaseException | None = None
        attempted = 0
        for position, index in enumerate(order):
            member = members[index]
            key = self._member_key(member)
            now = self._clock()
            if not self._available(key, now):
                continue
            attempted += 1
            try:
                return await getattr(member, method_name)(**kwargs)
            except BaseException as exc:
                if not should_failover(exc):
                    raise
                last_exc = exc
                reset_at = usage_limit_reset_at(exc, now=now)
                if key is not None and reset_at is not None:
                    self._cool_down(key, reset_at)
                    self._logger.warning(
                        "LLM account %s reached its usage limit; bypassing it until reset epoch %.0f",
                        key,
                        reset_at,
                    )
                remaining = len(order) - position - 1
                self._logger.warning(
                    "LLM member %d (%s/%s) failed on %s: %s%s",
                    index,
                    getattr(member, "provider", "unknown"),
                    getattr(member, "model", "unknown"),
                    method_name,
                    exc,
                    f"; trying next member ({remaining} left)" if remaining else "; no members left",
                )

        if last_exc is not None:
            raise last_exc
        if attempted == 0:
            raise RuntimeError("All LLM accounts are waiting for their reported quota reset")
        raise RuntimeError("LLM failover chain completed without a result")


def install_hindsight_patches() -> bool:
    try:
        from hindsight_api.engine.llm_wrapper import LLMProvider
        from hindsight_api.engine.multi_llm import MultiLLMProvider, _should_failover, logger
        from hindsight_api.engine.providers.codex_llm import CodexLLM
    except ModuleNotFoundError as exc:
        if exc.name == "hindsight_api" or (exc.name or "").startswith("hindsight_api."):
            return False
        raise

    hatchery_guard = HatcheryGuard()

    if not getattr(LLMProvider.__init__, "_hindsight_hatchery_aware", False):
        original_llm_init = LLMProvider.__init__

        def hatchery_aware_init(self, *args: Any, **kwargs: Any) -> None:
            original_llm_init(self, *args, **kwargs)
            hatchery_guard.prepare(self)

        hatchery_aware_init._hindsight_hatchery_aware = True  # type: ignore[attr-defined]
        LLMProvider.__init__ = hatchery_aware_init

    for method_name in ("call", "call_with_tools"):
        original_method = getattr(LLMProvider, method_name)
        if getattr(original_method, "_hindsight_hatchery_guarded", False):
            continue

        async def hatchery_guarded_call(
            self,
            *args: Any,
            _original_method: Callable[..., Any] = original_method,
            **kwargs: Any,
        ) -> Any:
            async def invoke(*call_args: Any, **call_kwargs: Any) -> Any:
                return await _original_method(self, *call_args, **call_kwargs)

            return await hatchery_guard.call(self, invoke, *args, **kwargs)

        hatchery_guarded_call._hindsight_hatchery_guarded = True  # type: ignore[attr-defined]
        setattr(LLMProvider, method_name, hatchery_guarded_call)

    if not getattr(CodexLLM.__init__, "_hindsight_account_aware", False):
        original_init = CodexLLM.__init__

        def account_aware_init(
            self,
            provider: str,
            api_key: str,
            base_url: str,
            model: str,
            reasoning_effort: str = "low",
            **kwargs: Any,
        ) -> None:
            with codex_home_environment(api_key):
                original_init(
                    self,
                    provider=provider,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    **kwargs,
                )

        account_aware_init._hindsight_account_aware = True  # type: ignore[attr-defined]
        CodexLLM.__init__ = account_aware_init

    if not getattr(MultiLLMProvider._dispatch, "_hindsight_quota_aware", False):
        dispatcher = QuotaAwareDispatcher(logger=logger)

        async def quota_aware_dispatch(self, method_name: str, **kwargs: Any) -> Any:
            return await dispatcher.dispatch(
                self._members,
                self._member_order(),
                method_name,
                kwargs,
                _should_failover,
            )

        quota_aware_dispatch._hindsight_quota_aware = True  # type: ignore[attr-defined]
        MultiLLMProvider._dispatch = quota_aware_dispatch

    logger.info("Installed account-aware, quota-cached Hindsight LLM failover")
    return True
