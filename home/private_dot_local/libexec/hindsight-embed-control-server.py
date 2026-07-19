#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
import functools
import os
import re
import subprocess
import sys
import time
from pathlib import Path


PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
COMPONENTS = frozenset({"daemon", "ui"})
STATES = frozenset({"running", "stopped"})
HATCHERY_PROVIDER_ID = "hatchery"
HATCHERY_RUNTIME_PROVIDER = "lmstudio"
HATCHERY_LABEL = "hatchery"
HATCHERY_BASE_URL = "http://hatchery.komodo-vector.ts.net:13305/v1"
HATCHERY_MODEL = "Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL"
CODEX_NISAVID_PROVIDER_ID = "codex-spark-nisavid"
CODEX_NISAVID_LABEL = "Codex Spark — personal (ivan@nisavid.io)"
CODEX_SYSTALYZE_PROVIDER_ID = "codex-spark-systalyze"
CODEX_SYSTALYZE_LABEL = "Codex Spark — work (ivan@systalyze.com)"
CODEX_RUNTIME_PROVIDER = "openai-codex"
CODEX_MODEL = "gpt-5.3-codex-spark"
CODEX_REASONING_EFFORT = "xhigh"
CODEX_HOME_ENV = "CODEX_HOME"
CODEX_REASONING_EFFORT_ENV = "HINDSIGHT_API_LLM_REASONING_EFFORT"
CODEX_NISAVID_HOME = Path.home() / ".hindsight/codex-nisavid"
CODEX_SYSTALYZE_HOME = Path.home() / ".hindsight/codex-systalyze"
CODEX_PROVIDER_HOMES = {
    CODEX_NISAVID_PROVIDER_ID: CODEX_NISAVID_HOME,
    CODEX_SYSTALYZE_PROVIDER_ID: CODEX_SYSTALYZE_HOME,
}


def normalize_profile(profile: str) -> str:
    normalized = "default" if profile in ("", "default") else profile
    if not PROFILE_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid profile name: {profile!r}")
    return normalized


def set_desired_state(root: Path, profile: str, component: str, state: str) -> None:
    profile = normalize_profile(profile)
    if component not in COMPONENTS:
        raise ValueError(f"invalid component: {component!r}")
    if state not in STATES:
        raise ValueError(f"invalid desired state: {state!r}")

    if root.is_symlink():
        raise ValueError("refusing symlinked desired-state path")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("refusing unsafe desired-state root")
    profiles = root / "profiles"
    if profiles.is_symlink():
        raise ValueError("refusing symlinked desired-state path")
    profiles.mkdir(exist_ok=True, mode=0o700)
    directory = profiles / profile
    if directory.is_symlink():
        raise ValueError("refusing symlinked desired-state path")
    directory.mkdir(exist_ok=True, mode=0o700)
    if not profiles.is_dir() or not directory.is_dir():
        raise ValueError("refusing unsafe desired-state path")
    root.chmod(0o700)
    profiles.chmod(0o700)
    directory.chmod(0o700)

    target = directory / component
    if target.is_symlink():
        raise ValueError("refusing symlinked desired-state file")
    temporary = directory / f".{component}.{os.getpid()}.{time.monotonic_ns()}"
    try:
        temporary.write_text(f"{state}\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _running_action(action, root: Path, components: tuple[str, ...]):
    @functools.wraps(action)
    def wrapped(profile: str):
        for component in components:
            set_desired_state(root, profile, component, "running")
        return action(profile)

    return wrapped


def _stopping_action(action, root: Path, component: str):
    @functools.wraps(action)
    def wrapped(profile: str):
        set_desired_state(root, profile, component, "stopped")
        try:
            result = action(profile)
        except Exception:
            set_desired_state(root, profile, component, "running")
            raise
        ok = getattr(result, "ok", True)
        running = getattr(result, "running", False)
        if not ok or running:
            set_desired_state(root, profile, component, "running")
        return result

    return wrapped


def install_lifecycle_hooks(service, desired_state_dir: Path) -> None:
    service.start_daemon = _running_action(service.start_daemon, desired_state_dir, ("daemon",))
    service.restart_daemon = _running_action(service.restart_daemon, desired_state_dir, ("daemon",))
    service.stop_daemon = _stopping_action(service.stop_daemon, desired_state_dir, "daemon")
    service.start_ui = _running_action(service.start_ui, desired_state_dir, ("daemon", "ui"))
    service.restart_ui = _running_action(service.restart_ui, desired_state_dir, ("daemon", "ui"))
    service.stop_ui = _stopping_action(service.stop_ui, desired_state_dir, "ui")


def install_provider_catalog(providers) -> None:
    catalog = tuple(
        provider
        for provider in providers.PROVIDER_CATALOG
        if provider.id != "openai-codex"
    )
    existing = {provider.id for provider in catalog}
    additions = []
    if CODEX_NISAVID_PROVIDER_ID not in existing:
        additions.append(
            providers.ProviderInfo(
                CODEX_NISAVID_PROVIDER_ID,
                CODEX_NISAVID_LABEL,
                False,
            )
        )
    if CODEX_SYSTALYZE_PROVIDER_ID not in existing:
        additions.append(
            providers.ProviderInfo(
                CODEX_SYSTALYZE_PROVIDER_ID,
                CODEX_SYSTALYZE_LABEL,
                False,
            )
        )
    if "claude-code" not in existing:
        additions.append(providers.ProviderInfo("claude-code", "Claude Code (subscription)", False))
    if HATCHERY_PROVIDER_ID not in existing:
        additions.append(
            providers.ProviderInfo(
                HATCHERY_PROVIDER_ID,
                HATCHERY_LABEL,
                False,
                HATCHERY_BASE_URL,
            )
        )
    providers.PROVIDER_CATALOG = (*catalog, *additions)


def _is_hatchery_config(config) -> bool:
    return (
        config.provider == HATCHERY_RUNTIME_PROVIDER
        and config.model == HATCHERY_MODEL
        and config.base_url == HATCHERY_BASE_URL
    )


def _codex_alias_for_config(config, env: dict[str, str]) -> str | None:
    if not (
        config.provider == CODEX_RUNTIME_PROVIDER
        and config.model == CODEX_MODEL
        and not config.base_url
        and env.get(CODEX_REASONING_EFFORT_ENV) == CODEX_REASONING_EFFORT
    ):
        return None
    codex_home = env.get(CODEX_HOME_ENV)
    for provider_id, home in CODEX_PROVIDER_HOMES.items():
        if codex_home == str(home):
            return provider_id
    return None


def install_provider_alias(service) -> None:
    original_get_profile_config = service.get_profile_config
    original_list_profiles = service.list_profiles
    original_save_llm_config = service.save_llm_config

    def display_config(config):
        if _is_hatchery_config(config):
            return replace(config, provider=HATCHERY_PROVIDER_ID)
        codex_alias = _codex_alias_for_config(
            config,
            service._read_raw_env(config.name),
        )
        if codex_alias:
            return replace(config, provider=codex_alias)
        return config

    def get_profile_config(name: str):
        return display_config(original_get_profile_config(name))

    def list_profiles():
        summaries = []
        for summary in original_list_profiles():
            config = get_profile_config(summary.name)
            if config.provider != summary.provider:
                summary = replace(
                    summary,
                    provider=config.provider,
                    model=config.model,
                )
            summaries.append(summary)
        return summaries

    def save_llm_config(
        name: str,
        provider: str,
        api_key: str | None,
        model: str | None,
        base_url: str | None,
        api_port: str | None = None,
        ui_port: str | None = None,
        api_version: str | None = None,
        cp_version: str | None = None,
    ):
        current = original_get_profile_config(name)
        current_env = service._read_raw_env(name)
        current_codex_alias = _codex_alias_for_config(current, current_env)
        codex_home = None
        if provider in CODEX_PROVIDER_HOMES:
            codex_home = CODEX_PROVIDER_HOMES[provider]
            provider = CODEX_RUNTIME_PROVIDER
            api_key = ""
            model = CODEX_MODEL
            base_url = ""
        elif provider == HATCHERY_PROVIDER_ID:
            provider = HATCHERY_RUNTIME_PROVIDER
            api_key = ""
            model = HATCHERY_MODEL
            base_url = HATCHERY_BASE_URL
        elif base_url is None and _is_hatchery_config(current):
            base_url = ""

        original_save_llm_config(
            name=name,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            api_port=api_port,
            ui_port=ui_port,
            api_version=api_version,
            cp_version=cp_version,
        )
        if codex_home is not None:
            env = service._read_raw_env(name)
            env[CODEX_HOME_ENV] = str(codex_home)
            env[CODEX_REASONING_EFFORT_ENV] = CODEX_REASONING_EFFORT
            service._write_raw_env(name, env)
        elif current_codex_alias:
            env = service._read_raw_env(name)
            env.pop(CODEX_HOME_ENV, None)
            env.pop(CODEX_REASONING_EFFORT_ENV, None)
            service._write_raw_env(name, env)
        return display_config(original_get_profile_config(name))

    service.get_profile_config = get_profile_config
    service.list_profiles = list_profiles
    service.save_llm_config = save_llm_config


def install_hooks(service, providers, desired_state_dir: Path) -> None:
    install_lifecycle_hooks(service, desired_state_dir)
    install_provider_catalog(providers)
    install_provider_alias(service)


def serve(port: int, desired_state_dir: Path) -> int:
    from hindsight_embed.control_center import providers, server, service

    install_hooks(service, providers, desired_state_dir)
    server.serve(port)
    return 0


def start(port: int, desired_state_dir: Path) -> int:
    from hindsight_embed.control_center import lifecycle

    lifecycle.get_or_create_token()
    if lifecycle.control_status(port).running:
        return 0

    log = lifecycle.log_file()
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "serve",
        "--port",
        str(port),
        "--desired-state-dir",
        str(desired_state_dir),
    ]
    with log.open("ab") as output:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
    lifecycle.pid_file().write_text(str(process.pid), encoding="utf-8")
    lifecycle.pid_file().chmod(0o600)

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if lifecycle.control_status(port).running:
            return 0
        if process.poll() is not None:
            return 1
        time.sleep(0.25)
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the managed Hindsight Embed Control Center.")
    parser.add_argument("command", choices=("start", "serve"))
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--desired-state-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    desired_state_dir = Path(os.path.abspath(args.desired_state_dir.expanduser()))
    if args.command == "serve":
        return serve(args.port, desired_state_dir)
    return start(args.port, desired_state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
