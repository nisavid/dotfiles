#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
import functools
import os
import re
import shlex
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
AUTOMATIC_PROVIDER_ID = "automatic"
AUTOMATIC_LABEL = "Automatic — work → personal → hatchery"
CODEX_NISAVID_PROVIDER_ID = "codex-spark-nisavid"
CODEX_NISAVID_LABEL = "Codex Spark — personal (ivan@nisavid.io)"
CODEX_SYSTALYZE_PROVIDER_ID = "codex-spark-systalyze"
CODEX_SYSTALYZE_LABEL = "Codex Spark — work (ivan@systalyze.com)"
CODEX_RUNTIME_PROVIDER = "openai-codex"
CODEX_MODEL = "gpt-5.3-codex-spark"
CODEX_REASONING_EFFORT = "xhigh"
CODEX_HOME_ENV = "CODEX_HOME"
CODEX_REASONING_EFFORT_ENV = "HINDSIGHT_API_LLM_REASONING_EFFORT"
LLM_API_KEY_ENV = "HINDSIGHT_API_LLM_API_KEY"
AUTOMATIC_ENV = {
    "HINDSIGHT_API_LLM_1_PROVIDER": CODEX_RUNTIME_PROVIDER,
    "HINDSIGHT_API_LLM_1_MODEL": CODEX_MODEL,
    "HINDSIGHT_API_LLM_1_REASONING_EFFORT": CODEX_REASONING_EFFORT,
    "HINDSIGHT_API_LLM_2_PROVIDER": HATCHERY_RUNTIME_PROVIDER,
    "HINDSIGHT_API_LLM_2_MODEL": HATCHERY_MODEL,
    "HINDSIGHT_API_LLM_2_BASE_URL": HATCHERY_BASE_URL,
    "HINDSIGHT_API_LLM_2_REASONING_EFFORT": "low",
    "HINDSIGHT_API_LLM_STRATEGY": '{"mode":"failover"}',
    "HINDSIGHT_API_LLM_MAX_RETRIES": "0",
    "HINDSIGHT_API_SKIP_LLM_VERIFICATION": "true",
}
AUTOMATIC_OWNED_ENV = frozenset(
    {
        *AUTOMATIC_ENV,
        "HINDSIGHT_API_LLM_1_API_KEY",
    }
)
CODEX_NISAVID_HOME = Path.home() / ".hindsight/codex-nisavid"
CODEX_SYSTALYZE_HOME = Path.home() / ".hindsight/codex-systalyze"
CODEX_PROVIDER_HOMES = {
    CODEX_NISAVID_PROVIDER_ID: CODEX_NISAVID_HOME,
    CODEX_SYSTALYZE_PROVIDER_ID: CODEX_SYSTALYZE_HOME,
}
CONTROL_STOP_HELPER = Path.home() / ".local/libexec/hindsight-embed-stop-profile-services.py"


def process_command(pid: int) -> str:
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def process_args(pid: int) -> list[str]:
    command = process_command(pid)
    if not command:
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return []


def has_arg_value(argv: list[str], name: str, value: str) -> bool:
    for index, arg in enumerate(argv):
        if arg == name and index + 1 < len(argv) and argv[index + 1] == value:
            return True
        if arg == f"{name}={value}":
            return True
    return False


def owns_hindsight_control(pid: int, port: int) -> bool:
    argv = process_args(pid)
    if not argv:
        return False
    managed_wrapper = str(Path.home() / ".local/libexec/hindsight-embed-control-server.py")
    has_upstream_marker = any(
        arg == "hindsight_embed.control_center.server" for arg in argv
    )
    has_managed_marker = managed_wrapper in argv and "serve" in argv
    has_port_marker = has_arg_value(argv, "--port", str(port))
    return (has_upstream_marker or has_managed_marker) and has_port_marker


def listener_pid(port: int) -> int | None:
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    pids = {int(line) for line in result.stdout.splitlines() if line.isdigit()}
    if len(pids) != 1:
        return None
    return pids.pop()


def managed_control_status(lifecycle, port: int) -> bool:
    if not lifecycle.control_status(port).running:
        return False
    pid_path = lifecycle.pid_file()
    if pid_path.is_symlink() or not pid_path.is_file():
        return False
    try:
        recorded_pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    actual_pid = listener_pid(port)
    return (
        actual_pid is not None
        and recorded_pid == actual_pid
        and owns_hindsight_control(actual_pid, port)
    )


def stop_existing_control(port: int) -> bool:
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(CONTROL_STOP_HELPER),
                "--mode",
                "stop-control",
                "--control-port",
                str(port),
                "--timeout",
                "30",
            ],
            timeout=40,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def prepare_control_start(lifecycle, port: int) -> bool:
    if managed_control_status(lifecycle, port):
        return False
    if not stop_existing_control(port):
        raise RuntimeError("could not safely stop inconsistent control listener")
    return True


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


def _converging_restart(action, start_action, is_running, timeout_seconds: float = 30):
    @functools.wraps(action)
    def wrapped(profile: str):
        result = action(profile)
        if getattr(result, "ok", True):
            return result

        # Hindsight's stop primitive reports failure after five seconds even
        # when the daemon is still completing a clean shutdown. Finish the
        # restart once that shutdown reaches its observable stopped state.
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not is_running(profile):
                return start_action(profile)
            time.sleep(0.25)
        return result

    return wrapped


def install_lifecycle_hooks(service, desired_state_dir: Path) -> None:
    start_daemon = service.start_daemon
    restart_daemon = service.restart_daemon
    daemon_client = getattr(service, "daemon_client", None)
    if daemon_client is not None:
        restart_daemon = _converging_restart(
            restart_daemon,
            start_daemon,
            daemon_client.is_daemon_running,
        )
    service.start_daemon = _running_action(start_daemon, desired_state_dir, ("daemon",))
    service.restart_daemon = _running_action(restart_daemon, desired_state_dir, ("daemon",))
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
    if AUTOMATIC_PROVIDER_ID not in existing:
        additions.append(
            providers.ProviderInfo(
                AUTOMATIC_PROVIDER_ID,
                AUTOMATIC_LABEL,
                False,
            )
        )
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


def _codex_home_marker(home: Path) -> str:
    return f"codex-home:{home}"


def _is_automatic_config(config, env: dict[str, str]) -> bool:
    return (
        config.provider == CODEX_RUNTIME_PROVIDER
        and config.model == CODEX_MODEL
        and env.get(LLM_API_KEY_ENV) == _codex_home_marker(CODEX_SYSTALYZE_HOME)
        and env.get("HINDSIGHT_API_LLM_1_API_KEY") == _codex_home_marker(CODEX_NISAVID_HOME)
        and all(env.get(key) == value for key, value in AUTOMATIC_ENV.items())
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
        if codex_home == str(home) or env.get(LLM_API_KEY_ENV) == _codex_home_marker(home):
            return provider_id
    return None


def install_provider_alias(service) -> None:
    original_get_profile_config = service.get_profile_config
    original_list_profiles = service.list_profiles
    original_save_llm_config = service.save_llm_config

    def display_config(config):
        env = service._read_raw_env(config.name)
        if _is_automatic_config(config, env):
            changes = {"provider": AUTOMATIC_PROVIDER_ID}
            if hasattr(config, "has_api_key"):
                changes.update(has_api_key=False, api_key_masked=None)
            return replace(config, **changes)
        if _is_hatchery_config(config):
            return replace(config, provider=HATCHERY_PROVIDER_ID)
        codex_alias = _codex_alias_for_config(
            config,
            env,
        )
        if codex_alias:
            changes = {"provider": codex_alias}
            if hasattr(config, "has_api_key"):
                changes.update(has_api_key=False, api_key_masked=None)
            return replace(config, **changes)
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
        current_is_automatic = _is_automatic_config(current, current_env)
        codex_home = None
        automatic = provider == AUTOMATIC_PROVIDER_ID
        if automatic:
            provider = CODEX_RUNTIME_PROVIDER
            api_key = _codex_home_marker(CODEX_SYSTALYZE_HOME)
            model = CODEX_MODEL
            base_url = ""
        elif provider in CODEX_PROVIDER_HOMES:
            codex_home = CODEX_PROVIDER_HOMES[provider]
            provider = CODEX_RUNTIME_PROVIDER
            api_key = _codex_home_marker(codex_home)
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
        env = service._read_raw_env(name)
        if automatic:
            env.pop(CODEX_HOME_ENV, None)
            env[CODEX_REASONING_EFFORT_ENV] = CODEX_REASONING_EFFORT
            env[LLM_API_KEY_ENV] = _codex_home_marker(CODEX_SYSTALYZE_HOME)
            env["HINDSIGHT_API_LLM_1_API_KEY"] = _codex_home_marker(CODEX_NISAVID_HOME)
            env.update(AUTOMATIC_ENV)
            service._write_raw_env(name, env)
        elif codex_home is not None:
            env[CODEX_HOME_ENV] = str(codex_home)
            env[CODEX_REASONING_EFFORT_ENV] = CODEX_REASONING_EFFORT
            env[LLM_API_KEY_ENV] = _codex_home_marker(codex_home)
            for key in AUTOMATIC_OWNED_ENV:
                env.pop(key, None)
            service._write_raw_env(name, env)
        elif current_codex_alias or current_is_automatic:
            env.pop(CODEX_HOME_ENV, None)
            env.pop(CODEX_REASONING_EFFORT_ENV, None)
            for key in AUTOMATIC_OWNED_ENV:
                env.pop(key, None)
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
    try:
        should_start = prepare_control_start(lifecycle, port)
    except RuntimeError:
        return 1
    if not should_start:
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
        if managed_control_status(lifecycle, port):
            return 0
        if process.poll() is not None:
            return 1
        time.sleep(0.25)
    return 1


def status(port: int) -> int:
    from hindsight_embed.control_center import lifecycle

    return 0 if managed_control_status(lifecycle, port) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the managed Hindsight Embed Control Center.")
    parser.add_argument("command", choices=("start", "status", "serve"))
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--desired-state-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    desired_state_dir = Path(os.path.abspath(args.desired_state_dir.expanduser()))
    if args.command == "serve":
        return serve(args.port, desired_state_dir)
    if args.command == "status":
        return status(args.port)
    return start(args.port, desired_state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
