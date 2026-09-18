"""Public-only chezmoi deployment tests; these never load the private source."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.provingkit_fixtures import fixture_selection

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    ".chezmoidata/provingkit.json",
    ".chezmoitemplates/provingkit-selection.tmpl",
    ".chezmoiexternals/provingkit.toml.tmpl",
    "dot_config/provingkit/selection-v1.json.tmpl",
    "private_dot_local/bin/executable_provingkit-installations",
    "run_after_sync-provingkit-installations.sh.tmpl",
)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class ProvingkitDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.home = self.base / "home"
        self.source = self.base / "source"
        self.home.mkdir()
        self.source.mkdir()
        for relative in SOURCE_FILES:
            destination = self.source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "home" / relative, destination)
        self.config = self.base / "chezmoi.toml"
        self.config.write_text("")
        self.environment = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "XDG_CACHE_HOME": str(self.base / "cache"),
            "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8",
        }

    def chezmoi(self, *args: str):
        return subprocess.run(
            [
                shutil.which("chezmoi"),
                "--source",
                str(self.source),
                "--destination",
                str(self.home),
                "--config",
                str(self.config),
                "--cache",
                str(self.base / "cache"),
                "--persistent-state",
                str(self.base / "state.boltdb"),
                "--no-tty",
                *args,
            ],
            cwd=self.base,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def select_fixture(self, case="a"):
        selection = fixture_selection(self.base / "publisher", case)
        (self.source / ".chezmoidata/provingkit.json").write_text(
            json.dumps(
                {
                    "provingkit": {
                        "selection": {"default": "portable-linux", "byHostname": {}},
                        "profiles": {"portable-linux": selection["profile"]},
                    },
                }
            )
        )
        return selection

    @unittest.skipUnless(
        os.uname().sysname == "Linux", "active materialization targets Linux"
    )
    def test_fresh_and_repeated_apply_fetch_pinned_artifacts_and_preserve_modes(self):
        self.select_fixture()
        first = self.chezmoi("apply", "--force")
        self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
        observed = json.loads(first.stdout)
        self.assertEqual(observed["outcome"], "materialized")
        self.assertEqual(observed["clients"]["cursor"]["runtime_acceptance"], "pending")
        installed = self.home / ".cursor/plugins/local/proseweaving"
        self.assertTrue(installed.is_dir())
        self.assertFalse(installed.is_symlink())
        self.assertEqual(
            (installed / "skills/fixture/check.sh").stat().st_mode & 0o777, 0o755
        )
        snapshot = {
            str(p): (p.read_bytes(), p.stat().st_mode & 0o777, p.stat().st_mtime_ns)
            for p in installed.rglob("*")
            if p.is_file()
        }
        again = self.chezmoi("apply", "--force")
        self.assertEqual(again.returncode, 0, again.stderr or again.stdout)
        self.assertEqual(
            snapshot,
            {
                str(p): (p.read_bytes(), p.stat().st_mode & 0o777, p.stat().st_mtime_ns)
                for p in installed.rglob("*")
                if p.is_file()
            },
        )

    def test_inactive_default_and_unsupported_platform_apply_without_artifacts(self):
        inactive = self.chezmoi("apply", "--force")
        self.assertEqual(inactive.returncode, 0, inactive.stderr)
        self.assertEqual(json.loads(inactive.stdout)["outcome"], "inactive")
        selected = self.select_fixture()
        selected["profile"]["platform"]["os"] = "unsupported-fixture-os"
        data = {
            "provingkit": {
                "selection": {"default": "portable-linux", "byHostname": {}},
                "profiles": {"portable-linux": selected["profile"]},
            }
        }
        (self.source / ".chezmoidata/provingkit.json").write_text(json.dumps(data))
        unsupported = self.chezmoi("apply", "--force")
        self.assertEqual(unsupported.returncode, 0, unsupported.stderr)
        self.assertEqual(
            json.loads(unsupported.stdout)["outcome"], "unsupported_platform"
        )
        self.assertFalse((self.home / ".local/share/provingkit").exists())
        self.assertFalse((self.home / ".cursor").exists())

    def test_default_profile_is_portable_to_another_hostname(self):
        self.select_fixture()
        projected = self.chezmoi(
            "execute-template",
            "--override-data",
            json.dumps(
                {
                    "chezmoi": {
                        "os": "linux",
                        "arch": "amd64",
                        "hostname": "another-new-machine",
                    },
                }
            ),
            '{{ includeTemplate "provingkit-selection.tmpl" . }}',
        )
        self.assertEqual(projected.returncode, 0, projected.stderr)
        self.assertEqual(json.loads(projected.stdout)["profile_name"], "portable-linux")
        data_path = self.source / ".chezmoidata/provingkit.json"
        data = json.loads(data_path.read_text())
        data["provingkit"]["selection"]["byHostname"]["another-new-machine"] = ""
        data_path.write_text(json.dumps(data))
        opted_out = self.chezmoi(
            "execute-template",
            "--override-data",
            json.dumps(
                {
                    "chezmoi": {
                        "os": "linux",
                        "arch": "amd64",
                        "hostname": "another-new-machine",
                    },
                }
            ),
            '{{ includeTemplate "provingkit-selection.tmpl" . }}',
        )
        self.assertEqual(opted_out.returncode, 0, opted_out.stderr)
        self.assertIsNone(json.loads(opted_out.stdout)["profile"])

    @unittest.skipUnless(
        os.uname().sysname == "Linux", "active materialization targets Linux"
    )
    def test_missing_extracted_artifact_and_installed_directory_are_recreated(self):
        selection = self.select_fixture()
        first = self.chezmoi("apply", "--force")
        self.assertEqual(first.returncode, 0, first.stderr)
        paths = [
            self.home / ".cursor/plugins/local/proseweaving",
            self.home
            / ".local/share/provingkit/artifacts/cursor"
            / selection["profile"]["artifacts"]["cursor"]["artifact_sha256"],
        ]
        for path in paths:
            self.assertTrue(path.resolve().is_relative_to(self.base.resolve()))
            self.assertFalse(path.is_symlink())
            shutil.rmtree(path)
        again = self.chezmoi("apply", "--force")
        self.assertEqual(again.returncode, 0, again.stderr or again.stdout)
        self.assertEqual(json.loads(again.stdout)["outcome"], "materialized")

    @unittest.skipUnless(
        os.uname().sysname == "Linux", "active materialization targets Linux"
    )
    def test_changed_published_archive_does_not_reach_the_client(self):
        from urllib.parse import urlparse

        selection = self.select_fixture()
        archive = Path(
            urlparse(selection["profile"]["artifacts"]["cursor"]["archive"]["url"]).path
        )
        archive.write_bytes(b"not the selected archive\n")
        result = self.chezmoi("apply", "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sha256 mismatch", result.stderr.lower())
        self.assertFalse((self.home / ".cursor").exists())
