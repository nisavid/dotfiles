#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


class StubDaemonEmbedManager:
    pass


hindsight_embed = types.ModuleType("hindsight_embed")
daemon_module = types.ModuleType("hindsight_embed.daemon_embed_manager")
daemon_module.DaemonEmbedManager = StubDaemonEmbedManager
sys.modules["hindsight_embed"] = hindsight_embed
sys.modules["hindsight_embed.daemon_embed_manager"] = daemon_module

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER_PATH = (
    REPO_ROOT
    / "home/private_dot_local/libexec/hindsight-embed-stop-profile-services.py"
)
SPEC = importlib.util.spec_from_file_location("hindsight_stop_helper", HELPER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {HELPER_PATH}")
HELPER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HELPER
SPEC.loader.exec_module(HELPER)


class ControlOwnershipTest(unittest.TestCase):
    def owns(self, argv: list[str]) -> bool:
        with mock.patch.object(HELPER, "process_args", return_value=argv):
            return HELPER.owns_hindsight_control(1234, 7878)

    def test_accepts_upstream_control_server(self) -> None:
        self.assertTrue(
            self.owns(
                [
                    "/usr/bin/python3",
                    "-m",
                    "hindsight_embed.control_center.server",
                    "--port",
                    "7878",
                ]
            )
        )

    def test_accepts_exact_managed_control_wrapper(self) -> None:
        wrapper = str(Path.home() / ".local/libexec/hindsight-embed-control-server.py")
        self.assertTrue(
            self.owns(
                [
                    "/usr/bin/python3",
                    wrapper,
                    "serve",
                    "--port",
                    "7878",
                    "--desired-state-dir",
                    str(Path.home() / ".local/state/hindsight-embed-launchd/desired"),
                ]
            )
        )

    def test_rejects_same_basename_outside_managed_location(self) -> None:
        self.assertFalse(
            self.owns(
                [
                    "/usr/bin/python3",
                    "/tmp/hindsight-embed-control-server.py",
                    "serve",
                    "--port",
                    "7878",
                ]
            )
        )


if __name__ == "__main__":
    unittest.main()
