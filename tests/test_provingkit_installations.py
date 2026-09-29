from __future__ import annotations

import hashlib
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
            "PROVINGKIT_TEST_LOCAL_ARTIFACTS": "1",
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

    def test_local_artifact_urls_require_explicit_fixture_mode(self) -> None:
        self.selection.write_text(json.dumps(fixture_selection(self.home)))
        self.environment.pop("PROVINGKIT_TEST_LOCAL_ARTIFACTS")

        code, report = self.run_command("validate")

        self.assertEqual((code, report["outcome"]), (64, "invalid_selection"))
        self.assertIn("HTTPS", report["message"])
        self.assertFalse((self.home / ".cursor").exists())

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
            "PROVINGKIT_TEST_LOCAL_ARTIFACTS": "1",
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

    def test_codex_alias_install_preserves_the_verified_canonical_artifact(
        self,
    ) -> None:
        self.use_native_clients()
        selection = fixture_selection(self.home, clients=("codex",))
        selection["profile"]["clients"]["codex"]["marketplace"] = "provingkit-local"
        root = artifact_root(self.home, selection, "agent-plugins")
        original = {
            str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode)
            for p in root.rglob("*")
            if p.is_file()
        }
        self.selection.write_text(json.dumps(selection))

        code, report = self.run_command("reconcile")

        self.assertEqual((code, report["outcome"]), (0, "converged"), report)
        observed = report["clients"]["codex"]
        self.assertEqual(observed["marketplace"]["name"], "provingkit-local")
        self.assertEqual(observed["members"]["proseweaving"]["content"], "match")
        self.assertIn(
            "/cache/provingkit-local/", observed["members"]["proseweaving"]["path"]
        )
        self.assertEqual(
            original,
            {
                str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode)
                for p in root.rglob("*")
                if p.is_file()
            },
        )
        repeated_code, repeated = self.run_command("reconcile")
        self.assertEqual(
            (repeated_code, repeated["outcome"]), (0, "converged"), repeated
        )
        self.assertEqual(repeated["clients"]["codex"]["actions"], [])

        different = fixture_selection(self.home, "b", ("codex",))
        repository = self.home / "repository"
        shutil.copytree(
            artifact_root(self.home, different, "agent-plugins"), repository
        )
        subprocess.run(
            ["git", "init", "--quiet", str(repository)],
            env=self.environment,
            check=True,
        )
        discovery = subprocess.run(
            [
                str(self.home / "bin/codex"),
                "plugin",
                "list",
                "--marketplace",
                "provingkit-local",
                "--json",
            ],
            env=self.environment,
            cwd=repository,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertTrue(json.loads(discovery.stdout)["installed"])
        code, rediscovered = self.run_command("status")
        self.assertEqual(
            (code, rediscovered["outcome"]), (0, "converged"), rediscovered
        )

    def test_codex_adopts_equivalent_shared_alias_without_native_mutations(
        self,
    ) -> None:
        self.use_native_clients()
        selection = fixture_selection(self.home, "six_a", ("codex",))
        selection["profile"]["clients"]["codex"]["marketplace"] = "provingkit-local"
        self.selection.write_text(json.dumps(selection))
        code, first = self.run_command("reconcile")
        self.assertEqual(code, 0, first)
        stable = Path(first["clients"]["codex"]["marketplace"]["root"])
        external = self.home / "retained-alpha"
        shutil.copytree(stable, external)
        retained_backup = self.home / "retained-alpha-backup"
        shutil.copytree(external, retained_backup)
        for member in selection["profile"]["artifact_slate"]:
            self.native_run(
                "codex", "plugin", "remove", member + "@provingkit-local", "--json"
            )
        self.native_run(
            "codex", "plugin", "marketplace", "remove", "provingkit-local", "--json"
        )
        self.native_run(
            "codex", "plugin", "marketplace", "add", str(external), "--json"
        )
        for member in selection["profile"]["artifact_slate"]:
            self.native_run(
                "codex", "plugin", "add", member + "@provingkit-local", "--json"
            )
        shutil.rmtree(stable)
        (self.home / ".local/state/provingkit/installations.json").unlink()
        before = json.loads(
            self.native_run(
                "codex", "plugin", "list", "--marketplace", "provingkit-local", "--json"
            ).stdout
        )
        cache = self.home / ".codex/plugins/cache/provingkit-local"
        before_files = {
            str(p.relative_to(cache)): (p.read_bytes(), p.stat().st_mode)
            for p in cache.rglob("*")
            if p.is_file()
        }
        selection["profile"]["clients"]["codex"]["members"] = {
            member: {"enabled": True}
            for member in ("proseweaving", "versionkeeping", "mergecraft")
        }
        self.selection.write_text(json.dumps(selection))

        code, report = self.run_command("reconcile")

        self.assertEqual((code, report["outcome"]), (0, "converged"), report)
        self.assertEqual(report["clients"]["codex"]["actions"], [])
        self.assertEqual(
            report["clients"]["codex"]["marketplace"]["root"], str(external)
        )
        self.assertFalse(stable.exists())
        after = json.loads(
            self.native_run(
                "codex", "plugin", "list", "--marketplace", "provingkit-local", "--json"
            ).stdout
        )
        self.assertEqual(before, after)
        self.assertEqual(
            before_files,
            {
                str(p.relative_to(cache)): (p.read_bytes(), p.stat().st_mode)
                for p in cache.rglob("*")
                if p.is_file()
            },
        )

        repeated_code, repeated = self.run_command("reconcile")
        self.assertEqual(
            (repeated_code, repeated["outcome"]), (0, "converged"), repeated
        )
        self.assertEqual(repeated["clients"]["codex"]["actions"], [])

        missing = Path(report["clients"]["codex"]["members"]["proseweaving"]["path"])
        shutil.rmtree(missing)
        code, repaired = self.run_command("reconcile")
        self.assertEqual((code, repaired["outcome"]), (0, "converged"), repaired)
        self.assertEqual(
            repaired["clients"]["codex"]["members"]["proseweaving"]["content"], "match"
        )
        self.assertEqual(
            repaired["clients"]["codex"]["marketplace"]["root"], str(external)
        )
        self.assertFalse(stable.exists())

        desired = fixture_selection(self.home, "preview", ("codex",))
        desired["profile"]["clients"]["codex"].update(
            selection["profile"]["clients"]["codex"]
        )
        self.selection.write_text(json.dumps(desired))
        code, refused = self.run_command("reconcile")
        self.assertEqual(code, 2, refused)
        self.assertEqual(refused["clients"]["codex"]["actions"], [])
        self.assertIn("unselected members", refused["clients"]["codex"]["message"])
        self.assertFalse(stable.exists())

        self.selection.write_text(json.dumps(selection))
        receipt = external / "RECEIPT.json"
        original_receipt = receipt.read_text()
        receipt.write_text(
            original_receipt.replace(
                '"parent_receipt_sha256": "', '"parent_receipt_sha256": "bad-'
            )
        )
        code, drift = self.run_command("reconcile")
        self.assertEqual(code, 2, drift)
        self.assertEqual(drift["clients"], {})

        # An external owner advances this same directory to the requested artifact.
        # Matching new bytes cannot authorize a transition of an adopted baseline.
        shutil.rmtree(external)
        shutil.copytree(artifact_root(self.home, desired, "agent-plugins"), external)
        catalog = external / ".agents/plugins/marketplace.json"
        catalog.write_bytes(
            catalog.read_bytes().replace(
                b'"name":"provingkit"', b'"name":"provingkit-local"'
            )
        )
        parent_bytes = (external / "RECEIPT.json").read_bytes()
        parent = json.loads(parent_bytes)
        (external / "RECEIPT.json").write_text(
            json.dumps(
                {
                    "schema": "provingkit-local-marketplace-projection-v1",
                    "source_commit": parent["source"]["commit"],
                    "parent_receipt_sha256": hashlib.sha256(parent_bytes).hexdigest(),
                    "change": {
                        "path": ".agents/plugins/marketplace.json",
                        "field": "name",
                        "from": "provingkit",
                        "to": "provingkit-local",
                    },
                    "plugin_slate": parent["plugin_slate"],
                },
                indent=2,
            )
            + "\n"
        )
        self.selection.write_text(json.dumps(desired))
        code, replaced_source = self.run_command("reconcile")
        self.assertEqual(code, 2, replaced_source)
        self.assertIn("adopted Codex source changed", replaced_source["message"])
        self.assertEqual(replaced_source["clients"], {})
        self.assertEqual(
            before_files,
            {
                str(p.relative_to(cache)): (p.read_bytes(), p.stat().st_mode)
                for p in cache.rglob("*")
                if p.is_file()
            },
        )

        # A coordinated selection of all members can rebind from the unchanged
        # baseline to the owned source; the old source is then no longer needed.
        shutil.rmtree(external)
        shutil.copytree(retained_backup, external)
        desired["profile"]["clients"]["codex"]["members"] = {
            member: {"enabled": True} for member in desired["profile"]["artifact_slate"]
        }
        self.selection.write_text(json.dumps(desired))
        code, advanced = self.run_command("reconcile")
        self.assertEqual((code, advanced["outcome"]), (0, "converged"), advanced)
        self.assertEqual(
            advanced["clients"]["codex"]["marketplace"]["root"], str(stable)
        )
        shutil.rmtree(external)
        code, independent = self.run_command("status")
        self.assertEqual((code, independent["outcome"]), (0, "converged"), independent)

    def test_claude_process_markers_do_not_change_payload_identity_and_are_backed_up(
        self,
    ) -> None:
        self.use_native_clients()
        selection = fixture_selection(self.home, clients=("claude",))
        self.selection.write_text(json.dumps(selection))
        code, initial = self.run_command("reconcile")
        self.assertEqual(code, 0, initial)
        installed = Path(
            initial["clients"]["claude"]["members"]["proseweaving"]["path"]
        )
        marker = installed / ".in_use/2147483000"
        marker.parent.mkdir()
        marker.write_text('{"pid":2147483000,"procStart":"12345"}')
        marker.chmod(0o644)

        code, observed = self.run_command("reconcile")

        self.assertEqual((code, observed["outcome"]), (0, "converged"), observed)
        self.assertEqual(observed["clients"]["claude"]["actions"], [])
        marker.unlink()
        second = marker.parent / "2147483001"
        second.write_text('{"pid":2147483001}')
        code, changed = self.run_command("status")
        self.assertEqual((code, changed["outcome"]), (0, "converged"), changed)
        self.selection.write_text(
            json.dumps(fixture_selection(self.home, "b", ("claude",)))
        )
        code, updated = self.run_command("reconcile")
        self.assertEqual((code, updated["outcome"]), (0, "converged"), updated)
        receipt = json.loads(
            (self.home / ".local/state/provingkit/installations.json").read_text()
        )
        backup = next(
            row for row in receipt["native_backups"] if row["member"] == "proseweaving"
        )
        self.assertEqual(
            (Path(backup["path"]) / ".in_use/2147483001").read_text(),
            '{"pid":2147483001}',
        )

    def test_claude_rejects_unrecognized_marker_shapes_before_native_actions(
        self,
    ) -> None:
        self.use_native_clients()
        self.selection.write_text(
            json.dumps(fixture_selection(self.home, clients=("claude",)))
        )
        code, initial = self.run_command("reconcile")
        self.assertEqual(code, 0, initial)
        installed = Path(
            initial["clients"]["claude"]["members"]["proseweaving"]["path"]
        )
        directory = installed / ".in_use"
        directory.mkdir()
        cases = [
            ("123", ""),
            ("123.tmp", '{"pid":123}'),
            ("123", '{"pid":124}'),
            ("123", '{"pid":123,"pid":123}'),
            ("123", '{"pid":123,"procStart":12}'),
            ("123", '{"pid":123,"extra":true}'),
            ("123", " " * 4097),
            ("123", "[]"),
        ]
        for name, content in cases:
            with self.subTest(name=name, content=content[:60]):
                marker = directory / name
                marker.write_text(content)
                code, refused = self.run_command("reconcile")
                self.assertEqual(code, 2, refused)
                self.assertEqual(refused["clients"]["claude"]["actions"], [])
                self.assertEqual(marker.read_text(), content)
                marker.unlink()
        nested = directory / "nested"
        nested.mkdir()
        code, refused = self.run_command("reconcile")
        self.assertEqual(code, 2, refused)
        self.assertEqual(refused["clients"]["claude"]["actions"], [])
        nested.rmdir()
        elsewhere = installed / "skills/fixture/.in_use/123"
        elsewhere.parent.mkdir()
        elsewhere.write_text('{"pid":123}')
        code, refused = self.run_command("reconcile")
        self.assertEqual(code, 2, refused)
        self.assertEqual(refused["clients"]["claude"]["actions"], [])

    def test_unknown_marketplace_identity_is_rejected(self) -> None:
        selection = fixture_selection(self.home, clients=("codex",))
        selection["profile"]["clients"]["codex"]["marketplace"] = "unrecognized"
        self.selection.write_text(json.dumps(selection))
        code, report = self.run_command("validate")
        self.assertEqual((code, report["outcome"]), (64, "invalid_selection"))

    def test_recorded_codex_marketplace_rename_is_refused_without_duplicate_installs(
        self,
    ) -> None:
        self.use_native_clients()
        selection = fixture_selection(self.home, clients=("codex",))
        self.selection.write_text(json.dumps(selection))
        code, original = self.run_command("reconcile")
        self.assertEqual(code, 0, original)
        receipt_path = self.home / ".local/state/provingkit/installations.json"
        receipt = json.loads(receipt_path.read_text())
        # Older observations record identity only in the client observation.
        receipt.pop("codex_marketplace", None)
        receipt.pop("native_paths", None)
        receipt_path.write_text(json.dumps(receipt))
        selection = fixture_selection(self.home, clients=("claude", "cursor", "codex"))
        selection["profile"]["clients"]["codex"]["marketplace"] = "provingkit-local"
        self.selection.write_text(json.dumps(selection))
        before = json.loads(
            self.native_run("codex", "plugin", "marketplace", "list", "--json").stdout
        )

        for _ in range(2):
            code, refused = self.run_command("reconcile")
            self.assertEqual(code, 2, refused)
            self.assertIn(
                "identity_transition_unavailable",
                refused["message"],
            )
            self.assertEqual(refused["clients"], {})
            self.assertFalse((self.home / ".cursor/plugins/local").exists())
            self.assertFalse((self.home / ".claude/plugins/cache").exists())
            self.assertFalse(
                (
                    self.home
                    / ".local/share/provingkit/marketplaces/agent-plugins-local"
                ).exists()
            )
        after = json.loads(
            self.native_run("codex", "plugin", "marketplace", "list", "--json").stdout
        )
        self.assertEqual(before, after)

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
        replaced = {
            client: (
                Path(before["clients"][client]["members"]["proseweaving"]["path"])
                / "skills/fixture/SKILL.md"
            ).read_bytes()
            for client in ("codex", "claude")
        }
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
        receipt = json.loads(
            (self.home / ".local/state/provingkit/installations.json").read_text()
        )
        for client in ("codex", "claude"):
            backups = [
                item
                for item in receipt.get("native_backups", [])
                if item["client"] == client and item["member"] == "proseweaving"
            ]
            self.assertTrue(backups, f"missing {client} recovery copy")
            self.assertEqual(
                (Path(backups[-1]["path"]) / "skills/fixture/SKILL.md").read_bytes(),
                replaced[client],
            )
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
        self.selection.write_text(json.dumps(original))
        code, baseline = self.run_command("reconcile")
        self.assertEqual((code, baseline["outcome"]), (0, "converged"), baseline)
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

        code, unrecognized = self.run_command("reconcile")
        self.assertEqual(code, 2, unrecognized)
        self.assertIn(
            "unrecognized selected cache", unrecognized["clients"]["claude"]["message"]
        )
        self.assertEqual(unrecognized["clients"]["claude"]["actions"], [])
        original["profile"]["clients"]["claude"]["members"] = desired["profile"][
            "clients"
        ]["claude"]["members"]
        self.selection.write_text(json.dumps(original))
        code, baseline = self.run_command("reconcile")
        self.assertEqual((code, baseline["outcome"]), (0, "converged"), baseline)
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

    def test_changed_selected_cache_is_preserved_with_or_without_prior_receipt(self):
        self.use_native_clients()
        self.selection.write_text(
            json.dumps(fixture_selection(self.home, clients=("codex", "claude")))
        )
        code, installed = self.run_command("reconcile")
        self.assertEqual(code, 0, installed)
        changed = []
        for client in ("codex", "claude"):
            path = Path(installed["clients"][client]["members"]["proseweaving"]["path"])
            skill = path / "skills/fixture/SKILL.md"
            skill.write_text("Unexplained local edits must survive.\n")
            changed.append(skill)
        for retained_receipt in (True, False):
            with self.subTest(retained_receipt=retained_receipt):
                if not retained_receipt:
                    (self.home / ".local/state/provingkit/installations.json").unlink()
                code, report = self.run_command("reconcile")
                self.assertEqual(code, 2, report)
                for client in ("codex", "claude"):
                    self.assertIn(
                        "unrecognized selected cache",
                        report["clients"][client]["message"],
                    )
                    self.assertEqual(report["clients"][client]["actions"], [])
                for skill in changed:
                    self.assertEqual(
                        skill.read_text(), "Unexplained local edits must survive.\n"
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

    def test_deleted_native_adapter_is_unavailable_and_preserves_its_receipt(
        self,
    ) -> None:
        self.use_native_clients()
        self.selection.write_text(
            json.dumps(fixture_selection(self.home, clients=("codex",)))
        )
        installed_code, installed = self.run_command("reconcile")
        self.assertEqual(installed_code, 0, installed)
        path = Path(installed["clients"]["codex"]["members"]["proseweaving"]["path"])
        adapter = path / ".codex-plugin/plugin.json"
        self.assertTrue(adapter.resolve().is_relative_to(self.home.resolve()))
        self.assertFalse(adapter.is_symlink())
        receipt_path = self.home / ".local/state/provingkit/installations.json"
        before = receipt_path.read_bytes()
        additions = json.loads(before)["native_additions"]
        self.assertIn(".codex-plugin/plugin.json", additions["proseweaving"])
        adapter.unlink()

        status_code, status = self.run_command("status")

        self.assertEqual(status_code, 2, status)
        self.assertEqual(status["clients"]["codex"]["outcome"], "unavailable")
        self.assertIn("native adapter drift", status["clients"]["codex"]["message"])
        self.assertEqual(receipt_path.read_bytes(), before)

        code, result = self.run_command("reconcile")

        self.assertEqual(code, 2, result)
        self.assertEqual(result["clients"]["codex"]["outcome"], "unavailable")
        self.assertEqual(result["clients"]["codex"]["actions"], [])
        self.assertFalse(adapter.exists())
        self.assertEqual(
            json.loads(receipt_path.read_text())["native_additions"], additions
        )

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
