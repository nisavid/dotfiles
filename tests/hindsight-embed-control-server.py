#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = (
    REPO_ROOT
    / "home/private_dot_local/libexec/hindsight-embed-control-server.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("hindsight_embed_control_server", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    needs_api_key: bool
    default_base_url: str | None = None


@dataclass(frozen=True)
class DaemonResult:
    ok: bool
    running: bool


@dataclass(frozen=True)
class UiResult:
    running: bool


class ControlServerHooksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state_dir = Path(self.temporary.name)
        self.providers = SimpleNamespace(
            ProviderInfo=ProviderInfo,
            PROVIDER_CATALOG=(ProviderInfo("openai", "OpenAI", True),),
        )
        self.service = SimpleNamespace(
            start_daemon=lambda _name: DaemonResult(ok=True, running=True),
            restart_daemon=lambda _name: DaemonResult(ok=True, running=True),
            stop_daemon=lambda _name: DaemonResult(ok=True, running=False),
            start_ui=lambda _name: UiResult(running=True),
            restart_ui=lambda _name: UiResult(running=True),
            stop_ui=lambda _name: UiResult(running=False),
        )
        self.module.install_hooks(self.service, self.providers, self.state_dir)

    def desired(self, profile: str, component: str) -> str:
        return (self.state_dir / "profiles" / profile / component).read_text().strip()

    def test_adds_subscription_providers_to_control_center_catalog(self) -> None:
        providers = {provider.id: provider for provider in self.providers.PROVIDER_CATALOG}
        self.assertFalse(providers["openai-codex"].needs_api_key)
        self.assertFalse(providers["claude-code"].needs_api_key)

    def test_daemon_stop_persists_intent_and_start_clears_it(self) -> None:
        self.service.stop_daemon("systalyze")
        self.assertEqual(self.desired("systalyze", "daemon"), "stopped")

        self.service.start_daemon("systalyze")
        self.assertEqual(self.desired("systalyze", "daemon"), "running")

    def test_failed_daemon_stop_restores_running_intent(self) -> None:
        original = self.service.stop_daemon
        self.service.stop_daemon = lambda _name: DaemonResult(ok=False, running=True)
        self.module.install_lifecycle_hooks(self.service, self.state_dir)

        self.service.stop_daemon("systalyze")
        self.assertEqual(self.desired("systalyze", "daemon"), "running")
        self.service.stop_daemon = original

    def test_ui_start_also_requests_its_required_daemon(self) -> None:
        self.service.stop_daemon("systalyze")
        self.service.stop_ui("systalyze")
        self.service.start_ui("systalyze")

        self.assertEqual(self.desired("systalyze", "daemon"), "running")
        self.assertEqual(self.desired("systalyze", "ui"), "running")

    def test_rejects_unsafe_profile_names(self) -> None:
        with self.assertRaises(ValueError):
            self.module.set_desired_state(self.state_dir, "../outside", "daemon", "stopped")

    def test_rejects_symlinked_state_root_without_following_it(self) -> None:
        outside = self.state_dir / "outside"
        outside.mkdir()
        linked = self.state_dir / "linked"
        linked.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(ValueError):
            self.module.set_desired_state(linked, "systalyze", "daemon", "stopped")
        self.assertFalse((outside / "profiles").exists())

    def test_main_preserves_symlink_for_the_guarded_writer(self) -> None:
        outside = self.state_dir / "outside-main"
        outside.mkdir()
        linked = self.state_dir / "linked-main"
        linked.symlink_to(outside, target_is_directory=True)
        captured: list[Path] = []
        args = SimpleNamespace(command="start", port=7878, desired_state_dir=linked)

        with (
            mock.patch.object(self.module, "parse_args", return_value=args),
            mock.patch.object(
                self.module,
                "start",
                side_effect=lambda _port, root: captured.append(root) or 0,
            ),
        ):
            self.assertEqual(self.module.main(), 0)

        self.assertEqual(captured, [linked.absolute()])


if __name__ == "__main__":
    unittest.main()
