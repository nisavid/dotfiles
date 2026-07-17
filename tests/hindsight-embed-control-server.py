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


@dataclass(frozen=True)
class ProfileConfig:
    name: str
    provider: str
    model: str
    base_url: str | None


@dataclass(frozen=True)
class ProfileSummary:
    name: str
    provider: str
    model: str


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
        self.profile_config = ProfileConfig(
            name="systalyze",
            provider="claude-code",
            model="claude-sonnet-5",
            base_url=None,
        )
        self.saved_configs: list[dict] = []

        def save_llm_config(**kwargs):
            self.saved_configs.append(kwargs)
            self.profile_config = ProfileConfig(
                name=kwargs["name"],
                provider=kwargs["provider"],
                model=kwargs["model"],
                base_url=kwargs["base_url"] or None,
            )
            return self.profile_config

        self.service = SimpleNamespace(
            start_daemon=lambda _name: DaemonResult(ok=True, running=True),
            restart_daemon=lambda _name: DaemonResult(ok=True, running=True),
            stop_daemon=lambda _name: DaemonResult(ok=True, running=False),
            start_ui=lambda _name: UiResult(running=True),
            restart_ui=lambda _name: UiResult(running=True),
            stop_ui=lambda _name: UiResult(running=False),
            get_profile_config=lambda _name: self.profile_config,
            list_profiles=lambda: [
                ProfileSummary(
                    name=self.profile_config.name,
                    provider=self.profile_config.provider,
                    model=self.profile_config.model,
                )
            ],
            save_llm_config=save_llm_config,
        )
        self.module.install_hooks(self.service, self.providers, self.state_dir)

    def desired(self, profile: str, component: str) -> str:
        return (self.state_dir / "profiles" / profile / component).read_text().strip()

    def test_adds_subscription_providers_to_control_center_catalog(self) -> None:
        providers = {provider.id: provider for provider in self.providers.PROVIDER_CATALOG}
        self.assertFalse(providers["openai-codex"].needs_api_key)
        self.assertFalse(providers["claude-code"].needs_api_key)
        self.assertEqual(providers["hatchery"].label, "hatchery")
        self.assertFalse(providers["hatchery"].needs_api_key)
        self.assertEqual(
            providers["hatchery"].default_base_url,
            "http://hatchery.komodo-vector.ts.net:13305/v1",
        )

    def test_hatchery_alias_saves_openai_compatible_runtime_config(self) -> None:
        result = self.service.save_llm_config(
            name="systalyze",
            provider="hatchery",
            api_key=None,
            model="ignored",
            base_url=None,
        )

        self.assertEqual(result.provider, "hatchery")
        self.assertEqual(
            self.saved_configs[-1],
            {
                "name": "systalyze",
                "provider": "lmstudio",
                "api_key": "",
                "model": "Qwen3.6-35B-A3B-MTP-GGUF-UD-Q4_K_XL",
                "base_url": "http://hatchery.komodo-vector.ts.net:13305/v1",
                "api_port": None,
                "ui_port": None,
                "api_version": None,
                "cp_version": None,
            },
        )
        self.assertEqual(self.service.list_profiles()[0].provider, "hatchery")

    def test_switching_from_hatchery_clears_its_base_url(self) -> None:
        self.service.save_llm_config(
            name="systalyze",
            provider="hatchery",
            api_key=None,
            model=None,
            base_url=None,
        )
        self.service.save_llm_config(
            name="systalyze",
            provider="claude-code",
            api_key=None,
            model="claude-sonnet-5",
            base_url=None,
        )

        self.assertEqual(self.saved_configs[-1]["provider"], "claude-code")
        self.assertEqual(self.saved_configs[-1]["base_url"], "")

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
