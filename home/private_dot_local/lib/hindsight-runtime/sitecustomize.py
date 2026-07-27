"""Install Ivan's provider policy into supported Hindsight API processes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
import importlib.util
from contextlib import contextmanager
import contextvars
import errno
import fcntl
import functools
import inspect
import json
import logging
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import time
from typing import Any


_ALLOW_ACL = re.compile(r"^\s*\d+:.*\sallow\s")
_AUTH_LOCK_TIMEOUT_SECONDS = 10.0
_RELEASE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}$")
_CODEX_AUTH_FILE_CONTEXT: contextvars.ContextVar[Path | None] = (
    contextvars.ContextVar("hindsight_codex_auth_file", default=None)
)


class _AuthLockTimeout(RuntimeError):
    pass


class _CodexResponseTrackingClient:
    def __init__(
        self,
        delegate: Any,
        owner: Any,
        response_context: contextvars.ContextVar[tuple[Any, Any] | None],
    ) -> None:
        self._delegate = delegate
        self._owner = owner
        self._response_context = response_context

    async def post(self, *args: Any, **kwargs: Any) -> Any:
        self._response_context.set(None)
        response = await self._delegate.post(*args, **kwargs)
        if getattr(response, "status_code", None) in {401, 403}:
            self._response_context.set((self._owner, response))
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_delegate", "_owner", "_response_context"}:
            object.__setattr__(self, name, value)
        else:
            setattr(self._delegate, name, value)


class _CodexRefreshTrackingClient:
    def __init__(self, delegate: Any, owner: Any) -> None:
        self._delegate = delegate
        self._owner = owner

    def post(self, *args: Any, **kwargs: Any) -> Any:
        self._owner._hindsight_last_refresh_response = None
        response = self._delegate.post(*args, **kwargs)
        self._owner._hindsight_last_refresh_response = response
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_delegate", "_owner"}:
            object.__setattr__(self, name, value)
        else:
            setattr(self._delegate, name, value)


def _reject_allow_acl(path: Path, label: str) -> None:
    result = subprocess.run(
        ["/bin/ls", "-lde", os.fspath(path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0 or any(
        _ALLOW_ACL.search(line) for line in result.stdout.splitlines()
    ):
        raise RuntimeError(f"{label} is not protected")


def _protected_directory(
    path: Path,
    label: str,
    *,
    private: bool = False,
) -> None:
    metadata = path.stat(follow_symlinks=False)
    forbidden_mode = 0o077 if private else 0o022
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & forbidden_mode
    ):
        raise RuntimeError(f"{label} is not protected")
    _reject_allow_acl(path, label)


def _protected_directory_ancestry(
    path: Path,
    root: Path,
    label: str,
    *,
    private: bool = False,
) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise RuntimeError(f"{label} is outside its protected root") from error
    current = path
    while True:
        _protected_directory(current, label, private=private)
        if current == root:
            break
        current = current.parent


def _provider_policy_path(home: Path) -> Path:
    return home / ".config/hindsight-control-plane/provider-runtime-policy.json"


def _read_protected_file(path: Path, label: str) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_nlink != 1
            or metadata.st_size > 1024 * 1024
        ):
            raise RuntimeError(f"{label} is not protected")
        _reject_allow_acl(path, label)
        chunks = bytearray()
        while len(chunks) <= 1024 * 1024:
            chunk = os.read(descriptor, min(65536, 1024 * 1024 + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        if len(chunks) > 1024 * 1024:
            raise RuntimeError(f"{label} is too large")
        return bytes(chunks)
    finally:
        os.close(descriptor)


def _resolve_active_release(install_root: Path) -> Path:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate active release key")
            result[key] = value
        return result

    try:
        active = json.loads(
            _read_protected_file(
                install_root / "active.json",
                "Hindsight active release record",
            ),
            object_pairs_hook=strict_object,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        raise RuntimeError("Hindsight active release record is invalid") from error
    if (
        not isinstance(active, dict)
        or set(active)
        != {"version", "release_digest", "release_path"}
        or not isinstance(active.get("version"), str)
        or _RELEASE_VERSION.fullmatch(active["version"]) is None
        or not isinstance(active.get("release_digest"), str)
        or _RELEASE_DIGEST.fullmatch(active["release_digest"]) is None
        or not isinstance(active.get("release_path"), str)
    ):
        raise RuntimeError("Hindsight active release record is invalid")
    expected_relative = (
        f"releases/{active['version']}-{active['release_digest'][:16]}"
    )
    if active["release_path"] != expected_relative:
        raise RuntimeError("Hindsight active release path is invalid")
    releases_path = install_root / "releases"
    _protected_directory(install_root, "Hindsight installation root")
    _protected_directory(releases_path, "Hindsight releases root")
    releases_root = releases_path.resolve(strict=True)
    release = (install_root / expected_relative).resolve(strict=True)
    try:
        release.relative_to(releases_root)
    except ValueError as error:
        raise RuntimeError("Hindsight active release path is invalid") from error
    if release.parent != releases_root:
        raise RuntimeError("Hindsight active release path is invalid")
    return release


@contextmanager
def _exclusive_auth_lock(
    auth_file: Path,
    *,
    timeout_seconds: float = _AUTH_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    lock_file = auth_file.parent / ".hindsight-auth.lock"
    descriptor = os.open(
        lock_file,
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    acquired = False
    try:
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_nlink != 1
        ):
            raise RuntimeError("Hindsight Codex auth lock is not protected")
        _reject_allow_acl(lock_file, "Hindsight Codex auth lock")
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except InterruptedError:
                if time.monotonic() >= deadline:
                    raise _AuthLockTimeout(
                        "Timed out acquiring Hindsight Codex auth lock"
                    ) from None
                continue
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise _AuthLockTimeout(
                        "Timed out acquiring Hindsight Codex auth lock"
                    ) from None
                time.sleep(0.05)
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                if time.monotonic() >= deadline:
                    raise _AuthLockTimeout(
                        "Timed out acquiring Hindsight Codex auth lock"
                    ) from error
                time.sleep(0.05)
        yield
    finally:
        try:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _disk_codex_tokens(auth_file: Path) -> dict[str, str | None]:
    try:
        payload = json.loads(
            _read_protected_file(auth_file, "Hindsight OAuth home")
        )
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError("Hindsight OAuth home is invalid") from error
    if not isinstance(payload, dict) or payload.get("auth_mode") != "chatgpt":
        raise RuntimeError("Hindsight OAuth home is invalid")
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        raise RuntimeError("Hindsight OAuth home is invalid")
    selected: dict[str, str | None] = {
        key: value if isinstance((value := tokens.get(key)), str) else None
        for key in ("access_token", "refresh_token", "account_id")
    }
    if not selected.get("access_token"):
        raise RuntimeError("Hindsight OAuth home is invalid")
    return selected


def _install_codex_auth_runtime(
    manager_module: Any,
    *,
    cooldown_seconds: int,
) -> Callable[[Any], Any]:
    manager_type = manager_module.CodexAuthManager
    terminal_error = manager_module.CodexRefreshExpiredError
    terminal_refresh_codes = {
        "invalid_grant",
        "invalid_refresh_token",
        "refresh_token_expired",
        "refresh_token_invalid",
        "refresh_token_invalidated",
        "refresh_token_reused",
        "token_expired",
        "token_invalidated",
        "token_reused",
        *{
            str(code).lower().replace("-", "_")
            for code in getattr(
                manager_module,
                "_CODEX_TERMINAL_REFRESH_ERROR_CODES",
                (),
            )
        },
    }
    if getattr(manager_type, "_hindsight_auth_runtime", False):
        return manager_type._hindsight_manager_registry

    original_refresh = manager_type.refresh_tokens
    original_token_is_stale = manager_type._token_is_stale
    registry: dict[Path, Any] = {}
    registry_lock = threading.Lock()
    terminal_cooldowns: dict[Path, float] = {}
    next_cooldown_probes: dict[Path, float] = {}

    class _RefreshDelegateFailure(Exception):
        def __init__(self, error: OSError | RuntimeError) -> None:
            self.error = error

    def enter_terminal_cooldown(path: Path) -> None:
        retry_at = time.monotonic() + cooldown_seconds
        with registry_lock:
            terminal_cooldowns[path] = max(
                retry_at,
                terminal_cooldowns.get(path, 0.0),
            )
            next_cooldown_probes.pop(path, None)

    def auth_path(manager: Any) -> Path:
        path = Path(manager._auth_file)
        if not path.is_absolute():
            raise RuntimeError("Hindsight OAuth auth path is not absolute")
        return path.resolve(strict=False)

    def adopt_disk(manager: Any) -> bool:
        tokens = _disk_codex_tokens(auth_path(manager))
        credentials_changed = False
        for attribute in ("access_token", "refresh_token", "account_id"):
            value = tokens[attribute]
            if getattr(manager, attribute, None) != value:
                setattr(manager, attribute, value)
                if attribute in {"access_token", "refresh_token"}:
                    credentials_changed = True
        return credentials_changed

    def canonicalize(manager: Any) -> Any:
        client = getattr(manager, "_http_client", None)
        if client is not None and not isinstance(
            client,
            _CodexRefreshTrackingClient,
        ):
            manager._http_client = _CodexRefreshTrackingClient(
                client,
                manager,
            )
        path = auth_path(manager)
        with registry_lock:
            existing = registry.get(path)
            if existing is None:
                registry[path] = manager
                return manager
        if existing is manager:
            return manager
        try:
            with _exclusive_auth_lock(path):
                adopt_disk(existing)
        except (OSError, RuntimeError):
            pass
        finally:
            close = getattr(manager, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logging.getLogger(__name__).debug(
                        "Discarded duplicate Codex auth manager failed to close",
                        exc_info=True,
                    )
        return existing

    def terminal_refresh_response(manager: Any) -> bool:
        response = getattr(
            manager,
            "_hindsight_last_refresh_response",
            None,
        )
        manager._hindsight_last_refresh_response = None
        if response is None:
            return False
        try:
            payload = response.json()
        except Exception:
            return False
        codes: set[str] = set()

        def collect(value: Any, depth: int = 0) -> None:
            if depth > 16:
                return
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {
                        "code",
                        "error",
                        "error_code",
                        "type",
                    } and isinstance(item, str):
                        codes.add(
                            item.lower().replace("-", "_")
                        )
                    collect(item, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    collect(item, depth + 1)

        collect(payload)
        return bool(
            codes & terminal_refresh_codes
        )

    def auth_available(manager: Any) -> bool:
        try:
            path = auth_path(manager)
        except (OSError, RuntimeError):
            return False
        now = time.monotonic()
        with registry_lock:
            retry_at = terminal_cooldowns.get(path, 0.0)
            next_probe_at = next_cooldown_probes.get(path, 0.0)
            if retry_at > now and next_probe_at > now:
                return False
            if retry_at > now:
                next_cooldown_probes[path] = now + 1.0
        if retry_at <= now:
            return True
        try:
            with _exclusive_auth_lock(path, timeout_seconds=0.0):
                if adopt_disk(manager):
                    with registry_lock:
                        terminal_cooldowns.pop(path, None)
                        next_cooldown_probes.pop(path, None)
                    return True
        except (OSError, RuntimeError):
            return False
        return False

    def locked_refresh(
        manager: Any,
        reason: str = "",
        *,
        force: bool = False,
    ) -> None:
        try:
            path = auth_path(manager)
        except (OSError, RuntimeError):
            raise terminal_error(
                "Codex OAuth home is invalid or unreadable"
            ) from None
        try:
            with _exclusive_auth_lock(path):
                try:
                    changed_on_disk = adopt_disk(manager)
                except (OSError, RuntimeError):
                    enter_terminal_cooldown(path)
                    raise terminal_error(
                        "Codex OAuth home is invalid or unreadable"
                    ) from None
                if changed_on_disk:
                    with registry_lock:
                        terminal_cooldowns.pop(path, None)
                        next_cooldown_probes.pop(path, None)
                    return
                now = time.monotonic()
                with registry_lock:
                    retry_at = terminal_cooldowns.get(path, 0.0)
                if retry_at > now:
                    raise terminal_error(
                        "Codex OAuth home is temporarily unavailable after "
                        "terminal authentication failure"
                    ) from None
                if not getattr(manager, "refresh_token", None):
                    enter_terminal_cooldown(path)
                    raise terminal_error(
                        "Codex OAuth home has no refresh credential"
                    ) from None
                try:
                    original_refresh(manager, reason=reason, force=force)
                except terminal_error:
                    enter_terminal_cooldown(path)
                    raise terminal_error(
                        "Codex OAuth refresh credential is terminally invalid"
                    ) from None
                except (OSError, RuntimeError) as error:
                    if terminal_refresh_response(manager):
                        enter_terminal_cooldown(path)
                        raise terminal_error(
                            "Codex OAuth refresh credential is "
                            "terminally invalid"
                        ) from None
                    raise _RefreshDelegateFailure(error) from error
        except _AuthLockTimeout:
            raise
        except terminal_error:
            raise
        except _RefreshDelegateFailure as failure:
            raise failure.error from None
        except (OSError, RuntimeError):
            enter_terminal_cooldown(path)
            raise terminal_error(
                "Codex OAuth home is invalid or unreadable"
            ) from None

    locked_refresh._hindsight_auth_runtime = True  # type: ignore[attr-defined]
    manager_type.refresh_tokens = locked_refresh

    def reactive_only_token_is_stale(
        manager: Any,
        skew_seconds: int = 0,
    ) -> bool:
        del manager, skew_seconds
        return False

    reactive_only_token_is_stale._hindsight_reactive_only = True  # type: ignore[attr-defined]
    manager_type._token_is_stale = reactive_only_token_is_stale
    manager_type._hindsight_original_token_is_stale = original_token_is_stale

    original_from_file = getattr(manager_type, "from_file", None)
    if callable(original_from_file):

        @classmethod
        def shared_from_file(
            cls: type[Any],
            auth_file: Path | None = None,
        ) -> Any:
            del cls
            selected_auth_file = (
                auth_file
                if auth_file is not None
                else _CODEX_AUTH_FILE_CONTEXT.get()
            )
            return canonicalize(original_from_file(selected_auth_file))

        manager_type.from_file = shared_from_file

    manager_type._hindsight_auth_runtime = True
    manager_type._hindsight_manager_registry = staticmethod(canonicalize)
    manager_type._hindsight_auth_available = staticmethod(auth_available)
    return canonicalize


def _install_shared_codex_manager(
    codex_type: type[Any],
    canonicalize: Callable[[Any], Any],
) -> None:
    original_init = codex_type.__init__
    if getattr(original_init, "_hindsight_shared_auth_manager", False):
        return

    @functools.wraps(original_init)
    def shared_manager_init(
        instance: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        original_init(instance, *args, **kwargs)
        instance._auth_manager = canonicalize(instance._auth_manager)

    shared_manager_init._hindsight_shared_auth_manager = True  # type: ignore[attr-defined]
    codex_type.__init__ = shared_manager_init


def _response_has_invalid_token(response: Any) -> bool:
    try:
        payload = response.json()
    except Exception:
        payload = None
    codes: set[str] = set()

    def collect(value: Any, depth: int = 0) -> None:
        if depth > 16:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"code", "error_code", "type"} and isinstance(
                    item, str
                ):
                    codes.add(item.lower().replace("-", "_"))
                collect(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                collect(item, depth + 1)

    collect(payload)
    headers = getattr(response, "headers", {}) or {}
    authenticate = " ".join(
        str(value).lower()
        for key, value in headers.items()
        if str(key).lower() == "www-authenticate"
    )
    return bool(
        codes
        & {
            "expired_token",
            "invalid_access_token",
            "invalid_token",
            "token_expired",
            "token_invalid",
        }
        or re.search(
            r'error\s*=\s*(?:"invalid_token"|invalid_token)(?=$|[\s,;])',
            authenticate,
        )
        is not None
    )


def _install_definitive_codex_refresh(codex_type: type[Any]) -> None:
    original_refresh = codex_type._refresh_oauth_tokens
    if getattr(original_refresh, "_hindsight_definitive_auth_errors", False):
        return
    response_context: contextvars.ContextVar[tuple[Any, Any] | None] = (
        contextvars.ContextVar(
            f"hindsight_codex_response_{id(codex_type)}",
            default=None,
        )
    )
    original_init = codex_type.__init__

    @functools.wraps(original_init)
    def response_tracking_init(
        instance: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        original_init(instance, *args, **kwargs)
        client = getattr(instance, "_client", None)
        if client is not None and not isinstance(
            client,
            _CodexResponseTrackingClient,
        ):
            instance._client = _CodexResponseTrackingClient(
                client,
                instance,
                response_context,
            )

    codex_type.__init__ = response_tracking_init

    parameters = inspect.signature(original_refresh).parameters.values()
    supports_controlled_canary = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or (
            parameter.name == "controlled_canary"
            and parameter.kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        )
        for parameter in parameters
    )

    def validate_refresh_authority(
        instance: Any,
        *,
        force: bool,
        controlled_canary: bool,
    ) -> None:
        active_error = sys.exc_info()[1]
        tracked = response_context.get()
        response_context.set(None)
        response = None
        if not controlled_canary:
            response = getattr(active_error, "response", None)
            if (
                response is None
                and tracked is not None
                and tracked[0] is instance
            ):
                response = tracked[1]
        status_code = getattr(response, "status_code", None)
        if controlled_canary:
            if not force:
                raise RuntimeError("Codex refresh canary authority is invalid")
            return
        if status_code == 401:
            return
        if status_code == 403 and _response_has_invalid_token(response):
            return
        raise RuntimeError(
            "Codex HTTP response is not a definitive token failure; "
            "OAuth refresh was not attempted"
        )

    if supports_controlled_canary:

        @functools.wraps(original_refresh)
        async def definitive_refresh(
            instance: Any,
            reason: str = "",
            *,
            force: bool = False,
            controlled_canary: bool = False,
        ) -> None:
            validate_refresh_authority(
                instance,
                force=force,
                controlled_canary=controlled_canary,
            )
            await original_refresh(
                instance,
                reason=reason,
                force=force,
                controlled_canary=controlled_canary,
            )

    else:

        @functools.wraps(original_refresh)
        async def definitive_refresh(
            instance: Any,
            reason: str = "",
            *,
            force: bool = False,
        ) -> None:
            validate_refresh_authority(
                instance,
                force=force,
                controlled_canary=False,
            )
            await original_refresh(instance, reason=reason, force=force)

    definitive_refresh._hindsight_definitive_auth_errors = True  # type: ignore[attr-defined]
    codex_type._refresh_oauth_tokens = definitive_refresh


def _install_codex_circuit_breaker(
    codex_type: type[Any],
    manager_type: type[Any],
    terminal_error: type[BaseException],
) -> None:
    for method_name in ("call", "call_with_tools"):
        original_method = getattr(codex_type, method_name, None)
        if not callable(original_method):
            continue
        if getattr(original_method, "_hindsight_auth_circuit_breaker", False):
            continue

        @functools.wraps(original_method)
        async def guarded_call(
            instance: Any,
            *args: Any,
            _original_method: Callable[..., Any] = original_method,
            **kwargs: Any,
        ) -> Any:
            available = await asyncio.to_thread(
                manager_type._hindsight_auth_available,
                instance._auth_manager,
            )
            if not available:
                raise terminal_error(
                    "Codex OAuth home is temporarily unavailable after "
                    "terminal authentication failure"
                )
            return await _original_method(instance, *args, **kwargs)

        guarded_call._hindsight_auth_circuit_breaker = True  # type: ignore[attr-defined]
        setattr(codex_type, method_name, guarded_call)


def _install_codex_embeddings_runtime(
    embeddings_module: Any,
    policy: Any,
    credential_resolver: Callable[[str], str],
    embedding_member_ids: tuple[str, ...],
) -> None:
    original_type = embeddings_module.CodexOAuthEmbeddings
    if getattr(original_type, "_hindsight_embeddings_runtime", False):
        return
    base_type = embeddings_module.Embeddings
    oauth_members = tuple(
        policy.member(member_id)
        for member_id in embedding_member_ids
    )
    if not oauth_members:
        raise RuntimeError("Hindsight embeddings policy has no OAuth members")
    constructor_parameters = inspect.signature(original_type).parameters
    explicit_home_parameter = next(
        (
            parameter
            for parameter in ("codex_home", "home")
            if parameter in constructor_parameters
        ),
        None,
    )

    class ManagedCodexEmbeddings(base_type):
        _hindsight_embeddings_runtime = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._members: list[tuple[Any, Any]] = []
            self._ready: list[tuple[Any, Any]] = []
            self._dimension: int | None = None
            for member in oauth_members:
                locator = member.credential_locator
                if locator is None:
                    continue
                try:
                    home = Path(credential_resolver(locator))
                    if not home.is_absolute():
                        raise RuntimeError("OAuth home is not absolute")
                    if explicit_home_parameter is not None:
                        candidate = original_type(
                            *args,
                            **kwargs,
                            **{explicit_home_parameter: str(home)},
                        )
                    else:
                        auth_file_token = _CODEX_AUTH_FILE_CONTEXT.set(
                            home / "auth.json"
                        )
                        try:
                            candidate = original_type(*args, **kwargs)
                        finally:
                            _CODEX_AUTH_FILE_CONTEXT.reset(auth_file_token)
                    manager = getattr(candidate, "_auth_manager", None)
                    if manager is None or not hasattr(manager, "_auth_file"):
                        raise RuntimeError(
                            "Codex embeddings member did not expose retained "
                            "OAuth auth state"
                        )
                    candidate_auth_file = Path(manager._auth_file).resolve(
                        strict=False
                    )
                    expected_auth_file = (home / "auth.json").resolve(
                        strict=False
                    )
                    if candidate_auth_file != expected_auth_file:
                        raise RuntimeError(
                            "Codex embeddings member did not retain its "
                            "assigned OAuth home"
                        )
                    self._members.append((member, candidate))
                except Exception:
                    logging.getLogger(
                        "hindsight_api.engine.embeddings"
                    ).warning(
                        "Codex embeddings member %s failed initialization",
                        member.id,
                    )
            if not self._members:
                raise RuntimeError(
                    "No managed Codex embeddings OAuth home could be initialized"
                )

        @property
        def provider_name(self) -> str:
            return "openai-codex"

        @property
        def dimension(self) -> int:
            if self._dimension is None:
                raise RuntimeError("Codex embeddings are not initialized")
            return self._dimension

        async def initialize(self) -> None:
            ready: list[tuple[Any, Any]] = []
            dimension: int | None = None
            for member, candidate in self._members:
                try:
                    await candidate.initialize()
                    candidate_dimension = candidate.dimension
                    if dimension is None:
                        dimension = candidate_dimension
                    elif candidate_dimension != dimension:
                        logging.getLogger(
                            "hindsight_api.engine.embeddings"
                        ).warning(
                            "Codex embeddings member %s dimension does not "
                            "match the primary; excluding member",
                            member.id,
                        )
                        continue
                    ready.append((member, candidate))
                except Exception:
                    logging.getLogger(
                        "hindsight_api.engine.embeddings"
                    ).warning(
                        "Codex embeddings member %s failed readiness",
                        member.id,
                    )
            if not ready:
                raise RuntimeError("All managed Codex embeddings members failed")
            self._ready = ready
            self._dimension = dimension

        def encode(self, texts: list[str]) -> list[list[float]]:
            last_error: Exception | None = None
            skipped_for_cooldown = False
            for member, candidate in self._ready:
                manager = getattr(candidate, "_auth_manager", None)
                available = getattr(
                    type(manager),
                    "_hindsight_auth_available",
                    None,
                )
                if (
                    manager is not None
                    and callable(available)
                    and not available(manager)
                ):
                    logging.getLogger(
                        "hindsight_api.engine.embeddings"
                    ).warning(
                        "Codex embeddings member %s is in authentication "
                        "cooldown; trying fallback",
                        member.id,
                    )
                    skipped_for_cooldown = True
                    continue
                try:
                    return candidate.encode(texts)
                except Exception as error:
                    response = getattr(error, "response", None)
                    status_code = getattr(response, "status_code", None)
                    definitive_auth_failure = status_code == 401 or (
                        status_code == 403
                        and _response_has_invalid_token(response)
                    )
                    refresh = getattr(manager, "refresh_tokens", None)
                    if definitive_auth_failure and callable(refresh):
                        failed_token = getattr(candidate, "api_key", None)
                        access_token = getattr(
                            manager,
                            "access_token",
                            None,
                        )
                        try:
                            if (
                                not isinstance(access_token, str)
                                or not access_token
                                or access_token == failed_token
                            ):
                                refresh(
                                    reason=(
                                        "reactive definitive authentication "
                                        "failure from embeddings API"
                                    ),
                                    force=True,
                                )
                            access_token = getattr(
                                manager,
                                "access_token",
                                None,
                            )
                            if (
                                isinstance(access_token, str)
                                and access_token
                                and access_token != failed_token
                            ):
                                candidate.api_key = access_token
                                client = getattr(candidate, "_client", None)
                                if client is not None:
                                    client.api_key = access_token
                                return candidate.encode(texts)
                        except Exception as retry_error:
                            error = retry_error
                    last_error = error
                    logging.getLogger(
                        "hindsight_api.engine.embeddings"
                    ).warning(
                        "Codex embeddings member %s failed; trying fallback",
                        member.id,
                    )
            if last_error is not None:
                raise last_error
            if skipped_for_cooldown:
                raise RuntimeError(
                    "All remaining managed Codex embeddings members are in "
                    "authentication cooldown"
                )
            raise RuntimeError("Managed Codex embeddings are not ready")

    embeddings_module.CodexOAuthEmbeddings = ManagedCodexEmbeddings


if importlib.util.find_spec("hindsight_api") is not None:
    home = Path.home().resolve(strict=True)
    install_root = home / ".local/opt/hindsight-control-plane"
    try:
        release = _resolve_active_release(install_root)
        release_lib = release / "lib"
        _protected_directory_ancestry(
            release,
            home,
            "active Hindsight release",
        )
        _protected_directory(release_lib, "active Hindsight release library")
        sys.path.insert(0, str(release_lib))

        from hindsight_memory_control_plane.canonical import strict_json_loads
        from hindsight_memory_control_plane.provider_runtime import (
            HindsightProviderAdapter,
            ProviderRuntimePolicy,
        )
        policy_path = _provider_policy_path(home)
        policy = ProviderRuntimePolicy.load(
            strict_json_loads(
                _read_protected_file(policy_path, "Hindsight provider policy")
            )
        )
        cooldown_raw = os.environ.get(
            "HINDSIGHT_CODEX_TERMINAL_AUTH_COOLDOWN_SECONDS",
        )
        embedding_order_raw = os.environ.get(
            "HINDSIGHT_EMBEDDING_FAILOVER_ORDER",
        )
        if (
            not isinstance(cooldown_raw, str)
            or re.fullmatch(r"[1-9][0-9]{0,3}", cooldown_raw) is None
            or not 1 <= int(cooldown_raw) <= 3600
            or embedding_order_raw
            != "work-codex,personal-codex"
        ):
            raise RuntimeError(
                "Hindsight Codex runtime policy is invalid"
            )
        terminal_auth_cooldown_seconds = int(cooldown_raw)
        embedding_member_ids = tuple(
            embedding_order_raw.split(",")
        )
        oauth_homes = {
            "oauth-home:personal": home / ".hindsight/codex-nisavid",
            "oauth-home:work": home / ".hindsight/codex-systalyze",
        }

        def resolve_oauth_home(locator: str) -> str:
            selected = oauth_homes.get(locator)
            if selected is None:
                raise RuntimeError("unknown Hindsight OAuth-home locator")
            _protected_directory_ancestry(
                selected,
                home,
                "Hindsight OAuth home",
            )
            _protected_directory(
                selected,
                "Hindsight OAuth home",
                private=True,
            )
            auth = selected / "auth.json"
            _read_protected_file(auth, "Hindsight OAuth home")
            return str(selected)

        HindsightProviderAdapter(
            policy,
            credential_resolver=resolve_oauth_home,
        ).install()
        from hindsight_api.engine import embeddings as embeddings_module
        from hindsight_api.engine.providers import codex_auth
        from hindsight_api.engine.providers.codex_llm import CodexLLM

        canonicalize_manager = _install_codex_auth_runtime(
            codex_auth,
            cooldown_seconds=terminal_auth_cooldown_seconds,
        )
        _install_shared_codex_manager(CodexLLM, canonicalize_manager)
        _install_definitive_codex_refresh(CodexLLM)
        _install_codex_circuit_breaker(
            CodexLLM,
            codex_auth.CodexAuthManager,
            codex_auth.CodexRefreshExpiredError,
        )
        _install_codex_embeddings_runtime(
            embeddings_module,
            policy,
            resolve_oauth_home,
            embedding_member_ids,
        )
    except Exception as error:
        raise SystemExit(
            f"Hindsight provider policy failed closed: {type(error).__name__}"
        ) from None
