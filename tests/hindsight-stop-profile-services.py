#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import signal
import sys
import types
from pathlib import Path


class StubDaemonEmbedManager:
    pass


hindsight_embed = types.ModuleType("hindsight_embed")
daemon_module = types.ModuleType("hindsight_embed.daemon_embed_manager")
daemon_module.DaemonEmbedManager = StubDaemonEmbedManager
sys.modules["hindsight_embed"] = hindsight_embed
sys.modules["hindsight_embed.daemon_embed_manager"] = daemon_module

repo_dir = Path(__file__).resolve().parent.parent
helper_path = repo_dir / "home/private_dot_local/libexec/hindsight-embed-stop-profile-services.py"
spec = importlib.util.spec_from_file_location("hindsight_stop_helper", helper_path)
assert spec and spec.loader
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)

original_path = os.environ.get("PATH")
os.environ["PATH"] = "/usr/bin:/bin"
try:
    helper.ensure_system_tool_path()
    assert os.environ["PATH"].split(os.pathsep)[:2] == ["/usr/sbin", "/sbin"]
finally:
    if original_path is None:
        os.environ.pop("PATH", None)
    else:
        os.environ["PATH"] = original_path


class FakeManager:
    def __init__(self) -> None:
        self.listener_pid = 43210
        self.port_busy = True

    def _kill_process(self, pid: int) -> bool:
        assert pid == self.listener_pid
        return False

    def _find_pid_on_port(self, port: int) -> int | None:
        assert port == 7979
        return self.listener_pid if self.port_busy else None

    def _is_port_in_use(self, port: int) -> bool:
        assert port == 7979
        return self.port_busy


manager = FakeManager()
signals: list[tuple[int, signal.Signals]] = []
original_kill = helper.os.kill


def fake_kill(pid: int, sent_signal: signal.Signals) -> None:
    signals.append((pid, sent_signal))
    if sent_signal == signal.SIGKILL:
        manager.port_busy = False


helper.os.kill = fake_kill
try:
    helper.stop_targets(manager, [helper.Target("API", 7979, manager.listener_pid)])
finally:
    helper.os.kill = original_kill

assert signals == [(manager.listener_pid, signal.SIGKILL)]
