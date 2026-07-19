#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from hindsight_embed.daemon_embed_manager import DaemonEmbedManager


@dataclass(frozen=True)
class Target:
    kind: str
    port: int
    pid: int
    cleanup_path: Path | None = None


class StopError(RuntimeError):
    pass


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


def process_has_open_file(pid: int, path: Path) -> bool:
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    expected = str(path)
    for line in result.stdout.splitlines()[1:]:
        columns = line.split()
        if columns and columns[-1] == expected:
            return True
    return False


def owns_hindsight_api(pid: int, paths) -> bool:
    # The API command does not include a profile name, so require evidence tied
    # to this profile's daemon log before taking ownership of the PID.
    return process_has_open_file(pid, paths.log)


def owns_hindsight_ui(pid: int, port: int, paths, api_url: str) -> bool:
    argv = process_args(pid)
    if argv:
        has_ui_marker = (
            any("hindsight-control-plane" in arg for arg in argv)
            or any("@vectorize-io/hindsight-control-plane" in arg for arg in argv)
        )
        has_port_marker = has_arg_value(argv, "--port", str(port))
        has_api_marker = has_arg_value(argv, "--api-url", api_url)
        if has_ui_marker and has_port_marker and has_api_marker:
            return True
    return process_has_open_file(pid, paths.ui_log)


def owns_hindsight_control(pid: int, port: int) -> bool:
    argv = process_args(pid)
    if not argv:
        return False
    managed_wrapper = str(
        Path.home() / ".local/libexec/hindsight-embed-control-server.py"
    )
    has_upstream_marker = any(
        arg == "hindsight_embed.control_center.server" for arg in argv
    )
    has_managed_marker = managed_wrapper in argv and "serve" in argv
    has_port_marker = has_arg_value(argv, "--port", str(port))
    return (has_upstream_marker or has_managed_marker) and has_port_marker


def fail_unverified(kind: str, port: int, pid: int) -> None:
    raise StopError(
        f"refusing to stop unverified listener on {kind} port {port} (pid {pid})"
    )


def find_owned_targets(manager: DaemonEmbedManager, paths, api_url: str, api_ports: set[int], ui_ports: set[int]) -> list[Target]:
    targets: list[Target] = []
    for port in sorted(ui_ports):
        pid = manager._find_pid_on_port(port)
        if pid is None:
            continue
        if not owns_hindsight_ui(pid, port, paths, api_url):
            fail_unverified("UI", port, pid)
        targets.append(Target("UI", port, pid))

    for port in sorted(api_ports):
        pid = manager._find_pid_on_port(port)
        if pid is None:
            continue
        if not owns_hindsight_api(pid, paths):
            fail_unverified("API", port, pid)
        targets.append(Target("API", port, pid))

    return targets


def find_control_target(manager: DaemonEmbedManager, port: int) -> list[Target]:
    pid_path = Path.home() / ".hindsight" / "control.pid"
    pid = manager._find_pid_on_port(port)
    if pid is None:
        pid_path.unlink(missing_ok=True)
        return []
    if not owns_hindsight_control(pid, port):
        fail_unverified("control", port, pid)
    return [Target("control", port, pid, pid_path)]


def stop_targets(
    manager: DaemonEmbedManager,
    targets: list[Target],
    *,
    timeout_seconds: float,
) -> None:
    killed: set[int] = set()
    for target in targets:
        if target.pid in killed:
            continue
        # Upstream returns False after waiting five seconds, even when the
        # process accepted SIGTERM and is still completing a clean shutdown.
        # The observable lifecycle contract is port convergence, not this
        # intermediate timeout.
        manager._kill_process(target.pid)
        killed.add(target.pid)

    ports = {target.port for target in targets}
    deadline = time.monotonic() + timeout_seconds
    while True:
        if not any(manager._is_port_in_use(port) for port in ports):
            for target in targets:
                if target.cleanup_path is not None:
                    target.cleanup_path.unlink(missing_ok=True)
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)

    busy = [str(port) for port in sorted(ports) if manager._is_port_in_use(port)]
    raise StopError("ports still listening after stop: " + ", ".join(busy))


def resolve_targets(manager: DaemonEmbedManager, args: argparse.Namespace) -> list[Target]:
    if args.mode == "stop-control":
        if args.control_port is None:
            raise StopError("stop-control mode requires --control-port")
        return find_control_target(manager, args.control_port)

    profile_manager = manager._profile_manager

    profile_exists = profile_manager.profile_exists(args.profile)
    if not profile_exists:
        if args.allow_unregistered_profile:
            pass
        elif args.require_profile:
            raise StopError(f"profile does not exist: {args.profile or 'default'}")
        else:
            return []

    paths = profile_manager.resolve_profile_paths(args.profile)
    recorded_ui_port = manager._read_recorded_ui_port(paths)
    api_url = manager.get_url(args.profile)

    api_ports: set[int] = set()
    ui_ports: set[int] = set()

    if args.mode in {"stop", "stop-api"}:
        api_ports.add(paths.port)
        if args.desired_api_port is not None:
            api_ports.add(args.desired_api_port)
    if args.mode in {"stop", "stop-ui"}:
        ui_ports.add(paths.ui_port)
        if recorded_ui_port is not None:
            ui_ports.add(recorded_ui_port)
        if args.desired_ui_port is not None:
            ui_ports.add(args.desired_ui_port)
    if args.mode in {"stop", "stop-api", "stop-ui"}:
        return find_owned_targets(manager, paths, api_url, api_ports, ui_ports)

    desired_api_port = args.desired_api_port
    desired_ui_port = args.desired_ui_port
    if desired_api_port is None or desired_ui_port is None:
        raise StopError("normalize mode requires desired API and UI ports")

    api_changed = paths.port != desired_api_port
    if api_changed:
        api_ports.add(paths.port)

    # If the API port changes, the existing UI may still point at the old API
    # URL even when it already occupies the canonical UI port. Restart it.
    ui_ports.add(paths.ui_port)
    if recorded_ui_port is not None:
        ui_ports.add(recorded_ui_port)
    ui_ports.discard(desired_ui_port)
    if api_changed:
        ui_ports.add(desired_ui_port)

    targets = find_owned_targets(manager, paths, api_url, api_ports, ui_ports)

    # Preflight the desired API/UI ports so Hindsight's own start path never
    # gets a chance to reclaim an unrelated service on the canonical ports.
    for kind, port in (("API", desired_api_port), ("UI", desired_ui_port)):
        pid = manager._find_pid_on_port(port)
        if pid is None:
            continue
        owned = owns_hindsight_api(pid, paths) if kind == "API" else owns_hindsight_ui(pid, port, paths, api_url)
        if not owned:
            fail_unverified(kind, port, pid)

    return targets


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely stop Hindsight profile services.")
    parser.add_argument("--mode", choices=("normalize", "stop", "stop-api", "stop-ui", "stop-control"), required=True)
    parser.add_argument("--profile", default="")
    parser.add_argument("--desired-api-port", type=int)
    parser.add_argument("--desired-ui-port", type=int)
    parser.add_argument("--control-port", type=int)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--require-profile", action="store_true")
    parser.add_argument("--allow-unregistered-profile", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        manager = DaemonEmbedManager()
        targets = resolve_targets(manager, args)
        if args.timeout <= 0:
            raise StopError("timeout must be greater than zero")
        stop_targets(manager, targets, timeout_seconds=args.timeout)
    except StopError as exc:
        print(f"hindsight-embed-stop-profile-services: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
