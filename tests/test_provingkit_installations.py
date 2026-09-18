from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.provingkit_fixtures import artifact_root, fixture_selection

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / "home/private_dot_local/bin/executable_provingkit-installations"


@unittest.skipUnless(
    sys.platform == "linux", "active installation fixtures target Linux"
)
class InstallationCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.selection = self.home / "selection.json"
        self.environment = os.environ | {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
        }

    def run_command(self, command: str) -> tuple[int, dict]:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(COMMAND),
                command,
                "--selection",
                str(self.selection),
                "--json",
            ],
            env=self.environment,
            cwd=self.home,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertTrue(result.stdout, result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_inactive_selection_performs_no_action(self) -> None:
        self.selection.write_text(
            json.dumps(
                {
                    "schema": "provingkit-installations-v1",
                    "profile_name": None,
                    "host_platform": {"os": "linux", "arch": "amd64"},
                    "profile": None,
                }
            )
        )

        code, report = self.run_command("reconcile")

        self.assertEqual(code, 0)
        self.assertEqual(report["outcome"], "inactive")
        self.assertEqual(list(self.home.iterdir()), [self.selection])

    def test_validate_accepts_pinned_projector_selection(self) -> None:
        self.selection.write_text(json.dumps(fixture_selection(self.home)))

        code, report = self.run_command("validate")

        self.assertEqual((code, report["outcome"]), (0, "valid"))
        self.assertFalse((self.home / ".cursor").exists())

    def test_unpinned_source_is_rejected(self) -> None:
        selection = fixture_selection(self.home)
        selection["profile"]["source"]["commit"] = "main"
        self.selection.write_text(json.dumps(selection))

        code, report = self.run_command("validate")

        self.assertEqual((code, report["outcome"]), (64, "invalid_selection"))

    def test_status_verifies_artifact_but_not_cursor_enablement(self) -> None:
        self.selection.write_text(json.dumps(fixture_selection(self.home)))

        code, report = self.run_command("status")

        self.assertEqual(code, 2)
        self.assertEqual(report["clients"]["cursor"]["artifact"], "verified")
        member = report["clients"]["cursor"]["members"]["proseweaving"]
        self.assertEqual(member["content"], "absent")
        self.assertEqual(member["enabled"], "unknown")
        self.assertFalse((self.home / ".cursor").exists())

    def test_cursor_reconcile_copies_clean_directories_and_repeated_apply_is_noop(
        self,
    ) -> None:
        selection = fixture_selection(self.home)
        self.selection.write_text(json.dumps(selection))
        sentinel = self.home / ".cursor/plugins/local/unselected/keep.txt"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("unselected member\n")

        code, report = self.run_command("reconcile")

        self.assertEqual((code, report["outcome"]), (0, "materialized"))
        self.assertEqual(report["clients"]["cursor"]["runtime_acceptance"], "pending")
        installed = self.home / ".cursor/plugins/local/proseweaving"
        self.assertFalse(installed.is_symlink())
        source = artifact_root(self.home, selection, "cursor") / "plugins/proseweaving"
        self.assertEqual(
            (installed / "skills/fixture/SKILL.md").read_bytes(),
            (source / "skills/fixture/SKILL.md").read_bytes(),
        )
        self.assertEqual(
            (installed / "skills/fixture/check.sh").stat().st_mode & 0o777, 0o755
        )
        self.assertEqual(
            report["clients"]["cursor"]["members"]["proseweaving"]["content"], "match"
        )
        before = {str(path): path.stat().st_mtime_ns for path in installed.rglob("*")}
        self.run_command("reconcile")
        self.assertEqual(
            before,
            {str(path): path.stat().st_mtime_ns for path in installed.rglob("*")},
        )
        self.assertEqual(sentinel.read_text(), "unselected member\n")

    def test_cursor_same_version_source_transition_is_recorded_and_old_directory_retained(
        self,
    ) -> None:
        self.selection.write_text(json.dumps(fixture_selection(self.home)))
        self.run_command("reconcile")
        installed = (
            self.home / ".cursor/plugins/local/proseweaving/skills/fixture/SKILL.md"
        )
        before = installed.read_bytes()
        selection = fixture_selection(self.home, "b")
        self.selection.write_text(json.dumps(selection))

        code, report = self.run_command("reconcile")

        self.assertEqual(code, 0, report)
        self.assertNotEqual(installed.read_bytes(), before)
        self.assertEqual(
            report["clients"]["cursor"]["members"]["proseweaving"]["content"], "match"
        )
        retained = list(
            (self.home / ".local/state/provingkit/backups").rglob("SKILL.md")
        )
        self.assertTrue(any(path.read_bytes() == before for path in retained))
        receipt = json.loads(
            (self.home / ".local/state/provingkit/installations.json").read_text()
        )
        self.assertEqual(receipt["selection"]["source"], selection["profile"]["source"])
        installed.unlink()
        _, drift = self.run_command("reconcile")
        self.assertEqual(drift["clients"]["cursor"]["outcome"], "unavailable")
        self.assertFalse(installed.exists())

    def use_native_clients(self) -> None:
        names = {
            client: os.environ.get("PROVINGKIT_TEST_" + client.upper())
            for client in ("codex", "claude")
        }
        if not all(names.values()):
            self.skipTest(
                "Set both PROVINGKIT_TEST_CODEX and PROVINGKIT_TEST_CLAUDE to frozen native executables"
            )
        binary_dir = self.home / "bin"
        binary_dir.mkdir()
        for name, executable in names.items():
            (binary_dir / name).symlink_to(executable)
        (self.home / ".codex").mkdir()
        (self.home / "tmp").mkdir()
        self.environment = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "CODEX_HOME": str(self.home / ".codex"),
            "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
            "NODE_COMPILE_CACHE": str(self.home / ".cache/node-compile"),
            "TMPDIR": str(self.home / "tmp"),
            "PATH": str(binary_dir) + ":/usr/bin:/bin:/usr/local/bin",
            "LANG": "C.UTF-8",
        }

    def test_native_fresh_install_observes_bytes_scopes_and_enablement(self) -> None:
        self.use_native_clients()
        selection = fixture_selection(self.home, clients=("codex", "claude"))
        selection["profile"]["clients"]["claude"]["members"]["versionkeeping"][
            "enabled"
        ] = False
        self.selection.write_text(json.dumps(selection))

        code, report = self.run_command("reconcile")

        self.assertEqual((code, report["outcome"]), (0, "converged"), report)
        for client in ("codex", "claude"):
            observation = report["clients"][client]
            self.assertEqual(observation["members"]["proseweaving"]["content"], "match")
            self.assertEqual(
                observation["members"]["versionkeeping"]["enabled"], client == "codex"
            )
            self.assertEqual(
                observation["members"]["proseweaving"]["scope"],
                "implicit_user" if client == "codex" else "user",
            )
        repeated_code, repeated = self.run_command("reconcile")
        self.assertEqual(
            (repeated_code, repeated["outcome"]), (0, "converged"), repeated
        )
        self.assertTrue(
            all(not item["actions"] for item in repeated["clients"].values()), repeated
        )

    def test_native_same_version_change_preserves_unselected_members_and_data(
        self,
    ) -> None:
        self.use_native_clients()
        selection = fixture_selection(self.home, clients=("codex", "claude"))
        selection["profile"]["clients"]["claude"]["members"]["versionkeeping"][
            "enabled"
        ] = False
        self.selection.write_text(json.dumps(selection))
        _, before = self.run_command("reconcile")
        marker = self.home / ".claude/plugins/data/proseweaving-provingkit/keep.txt"
        marker.parent.mkdir(parents=True)
        marker.write_text("persistent plugin data\n")
        sentinels = {
            client: before["clients"][client]["members"]["versionkeeping"]
            for client in ("codex", "claude")
        }
        old_skills = {
            client: (Path(value["path"]) / "skills/fixture/SKILL.md").read_bytes()
            for client, value in sentinels.items()
        }
        selection = fixture_selection(self.home, "b", ("codex", "claude"))
        for choice in selection["profile"]["clients"].values():
            choice["members"] = {"proseweaving": {"enabled": True}}
        self.selection.write_text(json.dumps(selection))

        code, report = self.run_command("reconcile")

        self.assertEqual((code, report["outcome"]), (0, "converged"), report)
        for client, value in sentinels.items():
            self.assertEqual(
                (Path(value["path"]) / "skills/fixture/SKILL.md").read_bytes(),
                old_skills[client],
            )
            commands = report["clients"][client]["actions"]
            self.assertFalse(
                any(
                    item["argv"][1:4] == ["plugin", "marketplace", "remove"]
                    for item in commands
                )
            )
        self.assertEqual(marker.read_text(), "persistent plugin data\n")
        for choice in selection["profile"]["clients"].values():
            choice["members"]["versionkeeping"] = {"enabled": True}
        selection["profile"]["clients"]["claude"]["members"]["versionkeeping"][
            "enabled"
        ] = False
        self.selection.write_text(json.dumps(selection))
        _, observed = self.run_command("status")
        for client, previous in sentinels.items():
            self.assertEqual(
                observed["clients"][client]["members"]["versionkeeping"], previous
            )

    def native_run(self, client: str, *arguments: str):
        result = subprocess.run(
            [str(self.home / "bin" / client), *arguments],
            env=self.environment,
            cwd=self.home,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return result

    def test_codex_rebind_requires_all_registered_members(self) -> None:
        self.use_native_clients()
        original = fixture_selection(self.home, clients=("codex",))
        root = artifact_root(self.home, original, "agent-plugins")
        self.native_run("codex", "plugin", "marketplace", "add", str(root), "--json")
        for member in ("proseweaving", "versionkeeping"):
            self.native_run("codex", "plugin", "add", member + "@provingkit", "--json")
        selected = fixture_selection(self.home, "b", ("codex",))
        selected["profile"]["clients"]["codex"]["members"] = {
            "proseweaving": {"enabled": True}
        }
        self.selection.write_text(json.dumps(selected))

        code, refused = self.run_command("reconcile")

        self.assertEqual(code, 2, refused)
        self.assertIn(
            "source_transition_unavailable", refused["clients"]["codex"]["message"]
        )
        self.assertFalse((self.home / ".local/share/provingkit/marketplaces").exists())
        selected["profile"]["clients"]["codex"]["members"]["versionkeeping"] = {
            "enabled": True
        }
        self.selection.write_text(json.dumps(selected))
        code, adopted = self.run_command("reconcile")
        self.assertEqual((code, adopted["outcome"]), (0, "converged"), adopted)
        self.assertTrue(root.exists())

    def test_claude_full_catalog_rebind_updates_only_the_selected_installations(
        self,
    ) -> None:
        self.use_native_clients()
        original = fixture_selection(self.home, "six_a", ("claude",))
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"unrelatedFixtureSetting": "keep"}))
        root = artifact_root(self.home, original, "claude")
        self.native_run(
            "claude", "plugin", "marketplace", "add", str(root), "--scope", "user"
        )
        for member in original["profile"]["artifact_slate"]:
            self.native_run(
                "claude",
                "plugin",
                "install",
                member + "@provingkit",
                "--scope",
                "user",
                "--json",
            )
        self.native_run(
            "claude",
            "plugin",
            "disable",
            "rolecasting@provingkit",
            "--scope",
            "user",
            "--json",
        )
        before = {
            row["id"]: row
            for row in json.loads(
                self.native_run("claude", "plugin", "list", "--json").stdout
            )
        }
        unselected = ("rolecasting", "tricritical", "artifact-customs")
        identities = {}
        for member in unselected:
            path = Path(before[member + "@provingkit"]["installPath"])
            identities[member] = {
                str(p.relative_to(path)): (p.read_bytes(), p.stat().st_mode & 0o777)
                for p in path.rglob("*")
                if p.is_file()
            }
        desired = fixture_selection(self.home, "preview", ("claude",))
        desired["profile"]["adoption"]["stage"] = "ad_hoc"
        desired["profile"]["clients"]["claude"]["members"] = {
            member: {"enabled": True}
            for member in ("proseweaving", "versionkeeping", "mergecraft")
        }
        self.selection.write_text(json.dumps(desired))

        code, report = self.run_command("reconcile")

        self.assertEqual((code, report["outcome"]), (0, "converged"), report)
        after = {
            row["id"]: row
            for row in json.loads(
                self.native_run("claude", "plugin", "list", "--json").stdout
            )
        }
        for member in unselected:
            self.assertEqual(
                before[member + "@provingkit"], after[member + "@provingkit"]
            )
            path = Path(after[member + "@provingkit"]["installPath"])
            self.assertEqual(
                identities[member],
                {
                    str(p.relative_to(path)): (p.read_bytes(), p.stat().st_mode & 0o777)
                    for p in path.rglob("*")
                    if p.is_file()
                },
            )
        self.assertFalse(
            any(
                item["argv"][1:4] == ["plugin", "marketplace", "remove"]
                for item in report["clients"]["claude"]["actions"]
            )
        )
        receipt = json.loads(
            (self.home / ".local/state/provingkit/installations.json").read_text()
        )
        self.assertEqual(
            set(receipt["source_transitions"][0]["unselected"]), set(unselected)
        )
        self.assertEqual(
            json.loads(settings.read_text())["unrelatedFixtureSetting"], "keep"
        )
        self.assertTrue(root.exists())

    def test_recorded_codex_shape_supports_a_versioned_cache_and_compatible_patch(
        self,
    ) -> None:
        # Constructed schema case; this does not claim a real 0.155.99 lifecycle.
        selected = fixture_selection(self.home, clients=("codex",))
        selected["profile"]["clients"]["codex"]["members"] = {
            "proseweaving": {"enabled": True}
        }
        self.selection.write_text(json.dumps(selected))
        source = artifact_root(self.home, selected, "agent-plugins")
        stable = self.home / ".local/share/provingkit/marketplaces/agent-plugins"
        shutil.copytree(source, stable)
        cache = self.home / ".codex/plugins/cache/provingkit/proseweaving/1.0.0"
        shutil.copytree(source / "plugins/proseweaving", cache)
        probe = json.loads(
            (
                ROOT / "tests/fixtures/provingkit-installations/native-probes.json"
            ).read_text()
        )["cases"]["initial/codex"]
        captured = [
            json.loads(item["stdout"])
            for item in probe["commands"]
            if item["argv"][1:3] == ["plugin", "list"]
            and item["returncode"] == 0
            and "--json" in item["argv"]
        ]
        row = next(value["installed"][0] for value in captured if value["installed"])
        row["version"] = "1.0.0"
        row["source"]["path"] = str(stable / "plugins/proseweaving")
        row["marketplaceSource"]["source"] = str(stable)
        responses = {
            "--version": "codex-cli 0.155.99",
            "plugin list --marketplace provingkit --json": json.dumps(
                {"installed": [row], "available": []}
            ),
            "plugin marketplace list --json": json.dumps(
                {
                    "marketplaces": [
                        {
                            "name": "provingkit",
                            "root": str(stable),
                            "marketplaceSource": row["marketplaceSource"],
                        }
                    ]
                }
            ),
        }
        response_file = self.home / "responses.json"
        response_file.write_text(json.dumps(responses))
        binary_dir = self.home / "schema-bin"
        binary_dir.mkdir()
        binary = binary_dir / "codex"
        binary.write_text(
            f"#!{sys.executable}\nimport json, sys\nfrom pathlib import Path\nprint(json.loads(Path({str(response_file)!r}).read_text())[' '.join(sys.argv[1:])])\n"
        )
        binary.chmod(0o755)
        self.environment |= {
            "PATH": str(binary_dir),
            "CODEX_HOME": str(self.home / ".codex"),
        }

        code, report = self.run_command("status")

        self.assertEqual((code, report["outcome"]), (0, "converged"), report)
        self.assertEqual(
            report["clients"]["codex"]["members"]["proseweaving"]["path"], str(cache)
        )
        row["version"] = "../unrecognized"
        responses["plugin list --marketplace provingkit --json"] = json.dumps(
            {"installed": [row], "available": []}
        )
        response_file.write_text(json.dumps(responses))
        code, unknown = self.run_command("status")
        self.assertEqual(code, 2)
        self.assertEqual(unknown["clients"]["codex"]["outcome"], "unavailable")

    def test_native_cache_loss_is_repaired_from_observed_absence(self) -> None:
        self.use_native_clients()
        self.selection.write_text(
            json.dumps(fixture_selection(self.home, clients=("codex", "claude")))
        )
        _, installed = self.run_command("reconcile")
        for client in ("codex", "claude"):
            path = Path(installed["clients"][client]["members"]["proseweaving"]["path"])
            self.assertTrue(path.resolve().is_relative_to(self.home.resolve()))
            self.assertFalse(path.is_symlink())
            shutil.rmtree(path)
        _, missing = self.run_command("status")
        self.assertTrue(
            all(
                value["members"]["proseweaving"]["content"] == "absent"
                for value in missing["clients"].values()
            )
        )

        code, repaired = self.run_command("reconcile")

        self.assertEqual((code, repaired["outcome"]), (0, "converged"), repaired)
        self.assertTrue(
            all(
                value["members"]["proseweaving"]["content"] == "match"
                for value in repaired["clients"].values()
            )
        )

    def test_native_generated_adapter_drift_is_unavailable(self) -> None:
        self.use_native_clients()
        self.selection.write_text(
            json.dumps(fixture_selection(self.home, clients=("codex",)))
        )
        _, installed = self.run_command("reconcile")
        path = Path(installed["clients"]["codex"]["members"]["proseweaving"]["path"])
        adapter = path / ".codex-plugin/plugin.json"
        generated = json.loads(adapter.read_text())
        generated["category"] = "Changed fixture"
        adapter.write_text(json.dumps(generated))

        code, result = self.run_command("reconcile")

        self.assertEqual(code, 2)
        self.assertEqual(result["clients"]["codex"]["outcome"], "unavailable")
        self.assertEqual(json.loads(adapter.read_text())["category"], "Changed fixture")

    def test_preview_selection_replaces_the_ad_hoc_stage_and_adds_selected_members(
        self,
    ) -> None:
        self.selection.write_text(json.dumps(fixture_selection(self.home)))
        self.run_command("reconcile")
        selected = fixture_selection(self.home, "preview")
        self.selection.write_text(json.dumps(selected))

        code, report = self.run_command("reconcile")

        self.assertEqual((code, report["outcome"]), (0, "materialized"), report)
        self.assertEqual(
            set(report["clients"]["cursor"]["members"]),
            set(selected["profile"]["artifact_slate"]),
        )
        receipt = json.loads(
            (self.home / ".local/state/provingkit/installations.json").read_text()
        )
        self.assertEqual(receipt["selection"]["adoption"]["stage"], "preview")

    def test_missing_native_client_is_explicitly_unavailable(self) -> None:
        self.environment["PATH"] = str(self.home / "empty-bin")
        self.selection.write_text(
            json.dumps(fixture_selection(self.home, clients=("codex", "claude")))
        )

        code, report = self.run_command("reconcile")

        self.assertEqual(code, 2)
        self.assertTrue(
            all(
                value["outcome"] == "unavailable"
                for value in report["clients"].values()
            )
        )
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse((self.home / ".claude").exists())

    def test_wrong_executable_mode_invalidates_the_artifact(self) -> None:
        selected = fixture_selection(self.home)
        (
            artifact_root(self.home, selected, "cursor")
            / "plugins/proseweaving/skills/fixture/check.sh"
        ).chmod(0o644)
        self.selection.write_text(json.dumps(selected))

        code, report = self.run_command("reconcile")

        self.assertEqual((code, report["outcome"]), (1, "artifact_invalid"))
        self.assertIn("modes differ", report["message"])
        self.assertFalse((self.home / ".cursor").exists())

    def test_cursor_disable_request_is_unavailable_without_copying_plugins(
        self,
    ) -> None:
        selected = fixture_selection(self.home)
        selected["profile"]["clients"]["cursor"]["members"]["proseweaving"][
            "enabled"
        ] = False
        self.selection.write_text(json.dumps(selected))
        code, report = self.run_command("reconcile")
        self.assertEqual(code, 2)
        self.assertEqual(report["clients"]["cursor"]["outcome"], "unavailable")
        self.assertFalse((self.home / ".cursor").exists())
        status_code, status = self.run_command("status")
        self.assertEqual(status_code, 2)
        self.assertEqual(status["clients"]["cursor"]["outcome"], "unavailable")

    def test_changed_artifact_bytes_stop_before_installation(self) -> None:
        selection = fixture_selection(self.home)
        root = artifact_root(self.home, selection, "cursor")
        (root / "plugins/proseweaving/skills/fixture/SKILL.md").write_text("changed\n")
        self.selection.write_text(json.dumps(selection))

        code, report = self.run_command("reconcile")

        self.assertEqual((code, report["outcome"]), (1, "artifact_invalid"))
        self.assertFalse((self.home / ".cursor").exists())


if __name__ == "__main__":
    unittest.main()
