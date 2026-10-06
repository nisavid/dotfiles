"""Render desktop bindings in a disposable home without account or service access."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = {
    "private_dot_local/bin/executable_proton-drive-desktop": ".local/bin/proton-drive-desktop",
    "dot_config/systemd/user/proton-drive-desktop.service": ".config/systemd/user/proton-drive-desktop.service",
    "private_dot_local/private_share/applications/proton-drive.desktop": ".local/share/applications/proton-drive.desktop",
}


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class DesktopDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.home = self.root / "home with spaces"
        self.source.mkdir()
        self.home.mkdir()
        for name in (*PAYLOAD, ".chezmoiignore"):
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "home" / name, target)
        self.config = self.root / "chezmoi.toml"
        self.config.write_text("")
        self.env = {
            "HOME": str(self.home), "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8", "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
        }

    def chezmoi(self, *args):
        return subprocess.run([
            shutil.which("chezmoi"), "--source", str(self.source),
            "--destination", str(self.home), "--config", str(self.config),
            "--cache", str(self.root / "cache"), "--persistent-state",
            str(self.root / "state.boltdb"), "--no-tty", *args,
        ], env=self.env, cwd=self.root, text=True, capture_output=True)

    def platform(self, name):
        ignore = self.source / ".chezmoiignore"
        result = self.chezmoi("execute-template", "--override-data",
                              '{"chezmoi":{"os":"' + name + '"}}',
                              ignore.read_text())
        self.assertEqual(result.returncode, 0, result.stderr)
        ignore.write_text(result.stdout)

    def documented_wiring(self, action):
        guide = (ROOT / "docs/PROTON_DRIVE.md").read_text()
        marker = f"# proton-drive-custom-xdg-links: {action}"
        lines = guide.splitlines()
        start = next(
            index for index, line in enumerate(lines) if line.strip() == marker
        )
        self.assertEqual("```sh", lines[start - 1].strip())
        end = next(
            index for index in range(start + 1, len(lines))
            if lines[index].strip() == "```"
        )
        return textwrap.dedent("\n".join(lines[start:end])) + "\n"

    def run_wiring(self, action, environment):
        return subprocess.run(
            ["/bin/sh"], input=self.documented_wiring(action), env=environment,
            cwd=self.root, text=True, capture_output=True,
        )

    def run_documented_root_selection(self, action, selected_root):
        wiring = self.documented_wiring(action)
        function_start = wiring.index("normalize_discovery_root() {")
        selection_end = wiring.index("\n\nfor discovery_destination", function_start)
        script = wiring[function_start:selection_end]
        script += '\nprintf \'%s\\n%s\\n\' "$unit_link" "$launcher_link"\n'
        environment = {
            **self.env,
            "XDG_CONFIG_HOME": selected_root,
            "XDG_DATA_HOME": selected_root,
        }
        return subprocess.run(
            ["/bin/sh"], input=script, env=environment, cwd=self.root,
            text=True, capture_output=True,
        )

    def test_linux_apply_installs_controls_without_activating_or_enrolling(self):
        self.platform("linux")
        marker = self.home / "existing-user-data"
        marker.write_text("preserve me\n")
        for _ in range(2):
            result = self.chezmoi("apply", "--force")
            self.assertEqual(result.returncode, 0, result.stderr)
        for source, target in PAYLOAD.items():
            self.assertEqual((self.home / target).read_bytes(),
                             (ROOT / "home" / source).read_bytes())
        self.assertTrue(os.access(self.home / ".local/bin/proton-drive-desktop", os.X_OK))
        self.assertEqual(marker.read_text(), "preserve me\n")
        self.assertEqual(sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*")
                                if p.is_file() or p.is_symlink()),
                         sorted([*PAYLOAD.values(), "existing-user-data"]))

    def test_documented_custom_xdg_links_are_conflict_safe_and_reversible(self):
        self.platform("linux")
        applied = self.chezmoi("apply", "--force")
        self.assertEqual(applied.returncode, 0, applied.stderr)

        custom_config = self.root / "custom config"
        custom_data = self.root / "custom data"
        unit_source = self.home / ".config/systemd/user/proton-drive-desktop.service"
        launcher_source = self.home / ".local/share/applications/proton-drive.desktop"
        unit_link = custom_config / "systemd/user/proton-drive-desktop.service"
        launcher_link = custom_data / "applications/proton-drive.desktop"

        unrelated = custom_data / "applications/keep.txt"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("preserve me\n")

        layouts = (
            ("both-custom", custom_config, custom_data),
            ("config-only", custom_config, None),
            ("data-only", None, custom_data),
            ("all-default", None, None),
        )
        for name, config_home, data_home in layouts:
            with self.subTest(layout=name):
                environment = {**self.env}
                environment.pop("XDG_CONFIG_HOME")
                environment.pop("XDG_DATA_HOME")
                if config_home is not None:
                    environment["XDG_CONFIG_HOME"] = str(config_home)
                if data_home is not None:
                    environment["XDG_DATA_HOME"] = str(data_home)
                destinations = (
                    (unit_source, unit_source if config_home is None else unit_link),
                    (launcher_source,
                     launcher_source if data_home is None else launcher_link),
                )

                for _ in range(2):
                    result = self.run_wiring("setup", environment)
                    self.assertEqual(result.returncode, 0, result.stderr)
                for source, destination in destinations:
                    self.assertTrue(source.is_file())
                    self.assertFalse(source.is_symlink())
                    if destination != source:
                        self.assertTrue(destination.is_symlink())
                        self.assertEqual(source, destination.resolve(strict=True))
                    self.assertEqual(source.read_bytes(), destination.read_bytes())

                for source_name in PAYLOAD:
                    source = self.source / source_name
                    source.write_bytes(source.read_bytes() + b"\n# disposable update\n")
                updated = self.chezmoi("apply", "--force")
                self.assertEqual(updated.returncode, 0, updated.stderr)
                for source, destination in destinations:
                    self.assertEqual(source.read_bytes(), destination.read_bytes())

                source_payloads = {
                    source: source.read_bytes()
                    for source in (unit_source, launcher_source)
                }
                for _ in range(2):
                    removed = self.run_wiring("remove", environment)
                    self.assertEqual(removed.returncode, 0, removed.stderr)
                for source, destination in destinations:
                    self.assertTrue(source.is_file())
                    self.assertFalse(source.is_symlink())
                    self.assertEqual(source_payloads[source], source.read_bytes())
                    if destination != source:
                        self.assertFalse(destination.exists() or destination.is_symlink())
                self.assertEqual("preserve me\n", unrelated.read_text())

        environment = {
            **self.env,
            "XDG_CONFIG_HOME": str(custom_config),
            "XDG_DATA_HOME": str(custom_data),
        }

        unit_link.write_text("conflicting unit\n")
        conflict = self.run_wiring("setup", environment)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertEqual("conflicting unit\n", unit_link.read_text())
        self.assertFalse(launcher_link.exists() or launcher_link.is_symlink())
        unit_link.unlink()

        other = self.root / "other launcher"
        other.write_text("other\n")
        launcher_link.symlink_to(other)
        conflict = self.run_wiring("setup", environment)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertEqual(other, launcher_link.resolve(strict=True))
        self.assertFalse(unit_link.exists() or unit_link.is_symlink())
        removal_conflict = self.run_wiring("remove", environment)
        self.assertNotEqual(removal_conflict.returncode, 0)
        self.assertEqual(other, launcher_link.resolve(strict=True))
        self.assertFalse(unit_link.exists() or unit_link.is_symlink())

    def test_documented_wiring_normalizes_trailing_separators(self):
        self.platform("linux")
        applied = self.chezmoi("apply", "--force")
        self.assertEqual(applied.returncode, 0, applied.stderr)

        default_config = self.home / ".config"
        default_data = self.home / ".local/share"
        custom_config = self.root / "custom config"
        custom_data = self.root / "custom data"
        unit_source = default_config / "systemd/user/proton-drive-desktop.service"
        launcher_source = default_data / "applications/proton-drive.desktop"
        unit_link = custom_config / "systemd/user/proton-drive-desktop.service"
        launcher_link = custom_data / "applications/proton-drive.desktop"

        layouts = (
            ("default-one", f"{default_config}/", f"{default_data}/",
             unit_source, launcher_source),
            ("default-repeated", f"{default_config}///", f"{default_data}////",
             unit_source, launcher_source),
            ("mixed-one", f"{custom_config}/", f"{default_data}/",
             unit_link, launcher_source),
            ("mixed-repeated", f"{default_config}///", f"{custom_data}////",
             unit_source, launcher_link),
        )
        for name, config_home, data_home, unit_destination, launcher_destination in layouts:
            with self.subTest(layout=name):
                environment = {
                    **self.env,
                    "XDG_CONFIG_HOME": config_home,
                    "XDG_DATA_HOME": data_home,
                }
                destinations = (
                    (unit_source, unit_destination),
                    (launcher_source, launcher_destination),
                )

                for _ in range(2):
                    result = self.run_wiring("setup", environment)
                    self.assertEqual(result.returncode, 0, result.stderr)
                for source, destination in destinations:
                    self.assertEqual(source.read_bytes(), destination.read_bytes())
                    if destination != source:
                        self.assertTrue(destination.is_symlink())
                        self.assertEqual(str(source), os.readlink(destination))

                for _ in range(2):
                    removed = self.run_wiring("remove", environment)
                    self.assertEqual(removed.returncode, 0, removed.stderr)
                for source, destination in destinations:
                    self.assertTrue(source.is_file())
                    self.assertFalse(source.is_symlink())
                    if destination != source:
                        self.assertFalse(destination.exists() or destination.is_symlink())

        for action in ("setup", "remove"):
            for selected_root in ("/", "////"):
                with self.subTest(action=action, selected_root=selected_root):
                    normalized = self.run_documented_root_selection(
                        action, selected_root
                    )
                    self.assertEqual(normalized.returncode, 0, normalized.stderr)
                    self.assertEqual(
                        normalized.stdout,
                        "/systemd/user/proton-drive-desktop.service\n"
                        "/applications/proton-drive.desktop\n",
                    )

    def test_non_linux_apply_omits_all_desktop_bindings(self):
        self.platform("darwin")
        result = self.chezmoi("apply", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in PAYLOAD.values():
            self.assertFalse((self.home / target).exists(), target)

    def test_dry_run_does_not_install_bindings(self):
        self.platform("linux")
        result = self.chezmoi("apply", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in PAYLOAD.values():
            self.assertFalse((self.home / target).exists(), target)


if __name__ == "__main__":
    unittest.main()
