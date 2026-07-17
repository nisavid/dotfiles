#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    existing = {provider.id for provider in providers.PROVIDER_CATALOG}
    additions = []
    if "openai-codex" not in existing:
        additions.append(providers.ProviderInfo("openai-codex", "OpenAI Codex (subscription)", False))
    if "claude-code" not in existing:
        additions.append(providers.ProviderInfo("claude-code", "Claude Code (subscription)", False))
    providers.PROVIDER_CATALOG = (*providers.PROVIDER_CATALOG, *additions)


def install_hooks(service, providers, desired_state_dir: Path) -> None:
    install_lifecycle_hooks(service, desired_state_dir)
    install_provider_catalog(providers)


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
