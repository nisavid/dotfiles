"""Installation-view exports through the public CLI in disposable homes."""

from __future__ import annotations

import json
import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.provingkit_fixtures import artifact_root, fixture_selection

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "home/private_dot_local/bin/executable_provingkit-installations"
PROCEDURE = "docs/agent-equipment/provingkit-installations.md"


@unittest.skipUnless(sys.platform == "linux", "export publication targets Linux")
class ExportCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.addCleanup(self.restore_access)
        self.home = self.base / "home"
        self.home.mkdir()
        self.selection = self.home / "selection.json"
        self.selected = fixture_selection(self.home, clients=("codex",))
        self.selection.write_text(json.dumps(self.selected))
        self.output = self.base / "export"
        self.environment = os.environ | {
            "HOME": str(self.home),
            "PROVINGKIT_TEST_LOCAL_ARTIFACTS": "1",
        }
        self.producer = self.base / "producer"
        for name in (SCRIPT, PROCEDURE):
            path = self.producer / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
            path.chmod((ROOT / name).stat().st_mode & 0o777)
        for arguments in (
            ("init", "-q"),
            ("config", "user.name", "Synthetic exporter fixture"),
            ("config", "user.email", "fixture@example.invalid"),
            ("add", SCRIPT, PROCEDURE),
            ("commit", "-qm", "Synthetic producer byte binding"),
        ):
            subprocess.run(
                ["git", "-C", str(self.producer), *arguments],
                check=True,
                env=self.environment,
                capture_output=True,
            )

    def restore_access(self) -> None:
        for root, directories, _files in os.walk(self.base):
            Path(root).chmod(0o700)
            for name in directories:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(0o700)

    def run_command(
        self, *arguments: str, fault: str | None = None
    ) -> tuple[int, dict]:
        argv = [sys.executable, "-I", "-B", str(self.producer / SCRIPT)]
        if fault is not None:
            wrapper = self.base / "filesystem-fault.py"
            copied_root = (
                "canonical" if fault == "canonical-write" else "agent-plugins-local"
            )
            injection = (
                "original = Path.write_bytes\n"
                "def write(path, data):\n"
                "    if "
                + repr(copied_root)
                + " in path.parts and path.name == 'SKILL.md':\n"
                "        data += b'filesystem fault'\n"
                "    return original(path, data)\n"
                "Path.write_bytes = write\n"
            )
            if fault in (
                "move-then-error",
                "extra-published-entry",
                "late-collision",
                "unsupported-publication",
            ):
                injection = (
                    "loader = ctypes.CDLL\n"
                    "def load(*args, **kwargs):\n"
                    "    lib = loader(*args, **kwargs)\n"
                    "    rename = lib.renameat2\n"
                    "    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]\n"
                    "    def call(*arguments):\n"
                    + (
                        "        destination = Path(sys.argv[sys.argv.index('--output-directory') + 1])\n        destination.mkdir()\n"
                        if fault == "late-collision"
                        else "        ctypes.set_errno(errno.EOPNOTSUPP)\n        return -1\n"
                        if fault == "unsupported-publication"
                        else ""
                    )
                    + "        result = rename(*arguments)\n"
                    "        if result == 0:\n"
                    + (
                        "            ctypes.set_errno(errno.EIO)\n            return -1\n"
                        if fault == "move-then-error"
                        else "            destination = Path(sys.argv[sys.argv.index('--output-directory') + 1])\n"
                        "            (destination / 'unlisted').write_bytes(b'filesystem fault')\n"
                        if fault == "extra-published-entry"
                        else "            pass\n"
                    )
                    + "        return result\n"
                    "    lib.renameat2 = call\n"
                    "    return lib\n"
                    "ctypes.CDLL = load\n"
                )
            elif fault == "selection-drift":
                injection = (
                    "original = Path.write_bytes\n"
                    "def write(path, data):\n"
                    "    if path.name == 'EXPORT.json':\n"
                    "        selected = Path(sys.argv[sys.argv.index('--selection') + 1])\n"
                    "        original(selected, selected.read_bytes() + b' ')\n"
                    "    return original(path, data)\n"
                    "Path.write_bytes = write\n"
                )
            elif fault == "late-stage-corruption":
                injection = (
                    "original = Path.write_bytes\n"
                    "def write(path, data):\n"
                    "    result = original(path, data)\n"
                    "    if path.name == 'EXPORT.json':\n"
                    "        target = next((path.parent / 'canonical/plugins').rglob('SKILL.md'))\n"
                    "        original(target, b'filesystem fault')\n"
                    "    return result\n"
                    "Path.write_bytes = write\n"
                )
            elif fault == "retained-evidence":
                injection = (
                    "original = Path.write_bytes\n"
                    "def write(path, data):\n"
                    "    if path.name == 'modes.tsv' and path.parent.name == 'evidence':\n"
                    "        data += b'filesystem fault'\n"
                    "    return original(path, data)\n"
                    "Path.write_bytes = write\n"
                )
            elif fault == "missing-primitive":
                injection = "ctypes.CDLL = lambda *args, **kwargs: object()\n"
            elif fault == "restrictive-umask":
                injection = "os.umask(0o777)\n"
            elif fault == "unreadable-published":
                injection = (
                    "original = Path.read_bytes\n"
                    "def read(path):\n"
                    "    if path.name == 'EXPORT.json' and path.parent.name == 'export':\n"
                    "        raise PermissionError('constructed readback failure')\n"
                    "    return original(path)\n"
                    "Path.read_bytes = read\n"
                )
            elif fault in ("foreign-receipt", "foreign-evidence", "foreign-directory"):
                conditions = {
                    "foreign-receipt": "path.name == 'RECEIPT.json' and 'artifacts' in path.parts",
                    "foreign-evidence": "path.name == 'modes.tsv' and 'evidence' in path.parts",
                    "foreign-directory": "'artifacts' in path.parts and path.name == "
                    + repr(
                        self.selected["profile"]["artifacts"]["agent-plugins"][
                            "artifact_sha256"
                        ]
                    ),
                }
                injection = (
                    "original = Path.lstat\n"
                    "def lstat(path, *args, **kwargs):\n"
                    "    value = original(path, *args, **kwargs)\n"
                    "    if " + conditions[fault] + ":\n"
                    "        value = os.stat_result(((value.st_mode & ~0o777) | "
                    + ("0o005" if fault == "foreign-directory" else "0o004")
                    + ", *value[1:]))\n"
                    "    return value\n"
                    "Path.lstat = lstat\n"
                )
            wrapper.write_text(
                "import ctypes, errno, os, runpy, sys\nfrom pathlib import Path\n"
                + injection
                + "source = sys.argv.pop(1)\nsys.argv[0] = source\n"
                "runpy.run_path(source, run_name='__main__')\n"
            )
            argv = [
                sys.executable,
                "-I",
                "-B",
                str(wrapper),
                str(self.producer / SCRIPT),
            ]
        result = subprocess.run(
            [*argv, "export-installation-view", *arguments],
            env=self.environment,
            cwd=self.home,
            text=True,
            capture_output=True,
            timeout=5,
        )
        self.assertTrue(result.stdout, result.stderr)
        return result.returncode, json.loads(result.stdout)

    def export(self, fault: str | None = None) -> tuple[int, dict]:
        return self.run_command(
            "--selection",
            str(self.selection),
            "--artifact-home",
            str(self.home),
            "--output-directory",
            str(self.output),
            fault=fault,
        )

    def test_export_requires_explicit_inputs_without_using_host_selection(self) -> None:
        active = self.home / ".config/provingkit/selection-v1.json"
        active.parent.mkdir(parents=True)
        active.write_bytes(self.selection.read_bytes())

        code, report = self.run_command()

        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "not-published")
        self.assertIsNone(report["staging_directory"])
        self.assertFalse(self.output.exists())

    def test_export_retains_canonical_and_fixed_local_trees_with_raw_evidence(
        self,
    ) -> None:
        source = artifact_root(self.home, self.selected, "agent-plugins")
        parent = (source / "RECEIPT.json").read_bytes()
        catalog_path = ".agents/plugins/marketplace.json"
        catalog = (source / catalog_path).read_bytes()
        artifact = self.selected["profile"]["artifacts"]["agent-plugins"]

        code, report = self.export()

        self.assertEqual((code, report["outcome"]), (0, "confirmed"))
        self.assertIsNone(report["staging_directory"])
        self.assertEqual(
            set(report),
            {
                "schema",
                "outcome",
                "output_directory",
                "staging_directory",
                "manifest_sha256",
                "reason",
            },
        )
        canonical = self.output / "canonical"
        local = self.output / "agent-plugins-local"
        self.assertEqual((canonical / "RECEIPT.json").read_bytes(), parent)
        self.assertEqual((canonical / catalog_path).read_bytes(), catalog)
        self.assertEqual(
            json.loads((local / catalog_path).read_bytes())["name"], "provingkit-local"
        )
        expected_receipt = {
            "schema": "provingkit-local-marketplace-projection-v1",
            "source_commit": self.selected["profile"]["source"]["commit"],
            "parent_receipt_sha256": artifact["receipt"]["sha256"],
            "change": {
                "path": catalog_path,
                "field": "name",
                "from": "provingkit",
                "to": "provingkit-local",
            },
            "plugin_slate": self.selected["profile"]["artifact_slate"],
        }
        self.assertEqual(
            (local / "RECEIPT.json").read_bytes(),
            (json.dumps(expected_receipt, indent=2) + "\n").encode(),
        )
        self.assertEqual(
            (self.output / "evidence/parent-receipt.json").read_bytes(), parent
        )
        self.assertEqual(
            (self.output / "evidence/local-receipt.json").read_bytes(),
            (local / "RECEIPT.json").read_bytes(),
        )
        evidence = (
            self.home
            / ".local/share/provingkit/evidence/agent-plugins"
            / artifact["artifact_sha256"]
        )
        self.assertEqual(
            (self.output / "evidence/modes.tsv").read_bytes(),
            (evidence / "modes.tsv").read_bytes(),
        )
        manifest_bytes = (self.output / "EXPORT.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        self.assertEqual(
            report["manifest_sha256"], hashlib.sha256(manifest_bytes).hexdigest()
        )
        self.assertEqual(manifest["schema"], "provingkit-installation-view-export-v1")
        self.assertEqual(
            set(manifest),
            {
                "schema",
                "producer",
                "selection",
                "source",
                "artifact_slate",
                "input",
                "payloads",
                "evidence",
                "layout",
                "correspondence",
            },
        )
        self.assertEqual(manifest["input"]["archive_bytes_measured"], False)
        self.assertEqual(
            manifest["selection"]["sha256"],
            hashlib.sha256(self.selection.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["payloads"]["canonical"]["tree_sha256"],
            artifact["artifact_sha256"],
        )
        self.assertEqual((source / catalog_path).read_bytes(), catalog)
        self.assertFalse((self.home / ".codex").exists())

    def test_changed_local_member_is_not_published_even_with_valid_original(
        self,
    ) -> None:
        code, report = self.export(fault="local-write")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "not-published")
        self.assertFalse(self.output.exists())
        self.assertTrue(Path(report["staging_directory"]).is_dir())

    def test_existing_destination_is_a_preserved_collision(self) -> None:
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_bytes(b"unrelated")

        code, report = self.export()

        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "collision")
        self.assertIsNone(report["staging_directory"])
        self.assertEqual(sentinel.read_bytes(), b"unrelated")

    def test_error_after_move_reports_unknown_completion_without_cleanup(self) -> None:
        code, report = self.export(fault="move-then-error")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "publication-unknown")
        self.assertTrue((self.output / "EXPORT.json").is_file())
        self.assertIsNotNone(report["manifest_sha256"])

    def test_input_output_overlap_is_rejected_before_staging(self) -> None:
        source = artifact_root(self.home, self.selected, "agent-plugins")
        self.output = source / "export"

        code, report = self.export()

        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "not-published")
        self.assertIsNone(report["staging_directory"])
        self.assertEqual(list(source.glob(".provingkit-export-*")), [])

    def test_selection_drift_prevents_publication(self) -> None:
        code, report = self.export(fault="selection-drift")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "not-published")
        self.assertFalse(self.output.exists())

    def test_retained_mode_evidence_must_match_the_original_pin(self) -> None:
        code, report = self.export(fault="retained-evidence")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "not-published")
        self.assertFalse(self.output.exists())

    def test_readonly_trees_match_the_independently_worked_export_record(self) -> None:
        fixture = ROOT / "tests/fixtures/provingkit-installations"
        buffers = json.loads((fixture / "export-example-buffers.json").read_bytes())
        expected = json.loads((fixture / "export-example.json").read_bytes())
        self.selection.write_bytes(buffers["selection_file"].encode())
        selected = json.loads(buffers["selection_file"])
        source = artifact_root(self.home, selected, "agent-plugins")
        (source / ".agents/plugins").mkdir(parents=True)
        for name, key in (
            (".agents/plugins/marketplace.json", "canonical_catalog"),
            ("RECEIPT.json", "canonical_root_receipt"),
        ):
            (source / name).write_bytes(buffers[key].encode())
            (source / name).chmod(0o444)
        for path in (source / ".agents/plugins", source / ".agents", source):
            path.chmod(0o555)
        evidence = (
            self.home
            / ".local/share/provingkit/evidence/agent-plugins"
            / expected["input"]["artifact_sha256"]
        )
        evidence.mkdir(parents=True)
        (evidence / "RECEIPT.json").write_bytes(
            buffers["canonical_root_receipt"].encode()
        )
        (evidence / "RECEIPT.json").chmod(0o600)
        (evidence / "modes.tsv").write_bytes(buffers["modes_file"].encode())

        code, report = self.export()

        self.assertEqual((code, report["outcome"]), (0, "confirmed"), report)
        actual = json.loads((self.output / "EXPORT.json").read_bytes())
        producer = actual.pop("producer")
        expected.pop("producer")
        self.assertEqual(actual, expected)
        self.assertEqual(
            (
                self.output / "agent-plugins-local/.agents/plugins/marketplace.json"
            ).read_bytes(),
            buffers["local_catalog"].encode(),
        )
        self.assertEqual(
            (self.output / "agent-plugins-local/RECEIPT.json").read_bytes(),
            buffers["local_root_receipt"].encode(),
        )
        self.assertEqual(
            producer["script_sha256"],
            hashlib.sha256((self.producer / SCRIPT).read_bytes()).hexdigest(),
        )
        self.assertEqual((source / "RECEIPT.json").stat().st_mode & 0o777, 0o444)
        self.assertEqual(source.stat().st_mode & 0o777, 0o555)

    def test_unlisted_published_entry_prevents_confirmation_and_is_preserved(
        self,
    ) -> None:
        code, report = self.export(fault="extra-published-entry")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "published-unconfirmed")
        self.assertEqual((self.output / "unlisted").read_bytes(), b"filesystem fault")

    def test_empty_destination_appearing_at_publication_is_not_replaced(self) -> None:
        code, report = self.export(fault="late-collision")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "collision")
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertTrue(Path(report["staging_directory"]).is_dir())

    def test_unsupported_filesystem_retains_the_owned_stage(self) -> None:
        code, report = self.export(fault="unsupported-publication")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "not-published")
        self.assertFalse(self.output.exists())
        self.assertTrue(Path(report["staging_directory"]).is_dir())

    def test_missing_no_replacement_support_refuses_before_staging(self) -> None:
        code, report = self.export(fault="missing-primitive")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "not-published")
        self.assertIsNone(report["staging_directory"])

    def test_successful_move_with_unreadable_manifest_is_unconfirmed(self) -> None:
        code, report = self.export(fault="unreadable-published")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "published-unconfirmed")
        self.assertTrue((self.output / "EXPORT.json").is_file())

    def test_access_through_other_bits_does_not_expand_supported_owner_modes(
        self,
    ) -> None:
        for fault in ("foreign-receipt", "foreign-evidence", "foreign-directory"):
            with self.subTest(fault=fault):
                code, report = self.export(fault=fault)
                self.assertNotEqual(code, 0)
                self.assertEqual(report["outcome"], "not-published")
                self.assertIsNone(report["staging_directory"])
                self.assertIn("owner access", report["reason"])

    def test_changed_canonical_copy_is_rejected_while_original_remains_valid(
        self,
    ) -> None:
        code, report = self.export(fault="canonical-write")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "not-published")
        self.assertFalse(self.output.exists())

    def test_changed_raw_receipt_is_rejected_before_staging(self) -> None:
        source = artifact_root(self.home, self.selected, "agent-plugins")
        (source / "RECEIPT.json").write_bytes(
            (source / "RECEIPT.json").read_bytes() + b" "
        )
        code, report = self.export()
        self.assertNotEqual(code, 0)
        self.assertIsNone(report["staging_directory"])

    def test_retained_evidence_fifos_are_rejected_before_staging(self) -> None:
        artifact = self.selected["profile"]["artifacts"]["agent-plugins"]
        evidence = (
            self.home
            / ".local/share/provingkit/evidence/agent-plugins"
            / artifact["artifact_sha256"]
        )
        for name in ("RECEIPT.json", "modes.tsv"):
            with self.subTest(name=name):
                path = evidence / name
                original = path.read_bytes()
                original_mode = path.stat().st_mode & 0o777
                path.unlink()
                os.mkfifo(path, 0o600)
                before = path.lstat()
                try:
                    code, report = self.export()
                    self.assertNotEqual(code, 0)
                    self.assertEqual(report["outcome"], "not-published")
                    self.assertIsNone(report["staging_directory"])
                    self.assertIsNone(report["manifest_sha256"])
                    self.assertFalse(self.output.exists())
                    self.assertEqual(list(self.base.glob(".provingkit-export-*")), [])
                    after = path.lstat()
                    self.assertTrue(stat.S_ISFIFO(after.st_mode))
                    self.assertEqual(
                        (after.st_dev, after.st_ino, after.st_mode),
                        (before.st_dev, before.st_ino, before.st_mode),
                    )
                finally:
                    path.unlink()
                    path.write_bytes(original)
                    path.chmod(original_mode)

    def test_selection_duplicate_fields_are_rejected_before_staging(self) -> None:
        raw = self.selection.read_bytes()
        self.selection.write_bytes(
            b'{"schema":"provingkit-installations-v1",' + raw[1:]
        )
        code, report = self.export()
        self.assertNotEqual(code, 0)
        self.assertIsNone(report["staging_directory"])
        self.assertIn("duplicate", report["reason"])

    def test_inactive_profile_cannot_export(self) -> None:
        self.selected.update(profile=None, profile_name=None)
        self.selection.write_text(json.dumps(self.selected))
        code, report = self.export()
        self.assertNotEqual(code, 0)
        self.assertIsNone(report["staging_directory"])

    def test_uncommitted_producer_files_cannot_export(self) -> None:
        path = self.producer / PROCEDURE
        path.write_bytes(path.read_bytes() + b"uncommitted change\n")
        code, report = self.export()
        self.assertNotEqual(code, 0)
        self.assertIsNone(report["staging_directory"])
        self.assertIn("uncommitted", report["reason"])

    def test_payload_symlink_is_rejected_before_staging(self) -> None:
        source = artifact_root(self.home, self.selected, "agent-plugins")
        (source / "link").symlink_to(self.selection)
        code, report = self.export()
        self.assertNotEqual(code, 0)
        self.assertIsNone(report["staging_directory"])
        self.assertTrue((source / "link").is_symlink())

    def test_special_directory_mode_is_rejected_before_staging(self) -> None:
        source = artifact_root(self.home, self.selected, "agent-plugins")
        source.chmod(0o1755)
        code, report = self.export()
        self.assertNotEqual(code, 0)
        self.assertIsNone(report["staging_directory"])
        self.assertEqual(source.stat().st_mode & 0o7777, 0o1755)

    def test_empty_directories_and_root_receipt_modes_are_retained(self) -> None:
        source = artifact_root(self.home, self.selected, "agent-plugins")
        (source / "empty").mkdir(mode=0o750)
        (source / "RECEIPT.json").chmod(0o440)
        code, report = self.export()
        self.assertEqual((code, report["outcome"]), (0, "confirmed"), report)
        manifest = json.loads((self.output / "EXPORT.json").read_bytes())
        for name in ("canonical", "agent-plugins-local"):
            self.assertEqual(list((self.output / name / "empty").iterdir()), [])
            self.assertEqual(
                (self.output / name / "empty").stat().st_mode & 0o777, 0o750
            )
            self.assertEqual(
                (self.output / name / "RECEIPT.json").stat().st_mode & 0o777, 0o440
            )
        self.assertIn(
            {"path": "empty", "mode": "0750"},
            manifest["payloads"]["canonical"]["inventory"]["directories"],
        )

    def test_selection_digest_measures_the_whole_supplied_buffer(self) -> None:
        raw = self.selection.read_bytes() + b"\n \n"
        self.selection.write_bytes(raw)
        code, report = self.export()
        self.assertEqual((code, report["outcome"]), (0, "confirmed"), report)
        manifest = json.loads((self.output / "EXPORT.json").read_bytes())
        self.assertEqual(
            manifest["selection"],
            {
                "profile_name": self.selected["profile_name"],
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
        )

    def test_preparation_is_writable_under_a_restrictive_umask(self) -> None:
        code, report = self.export(fault="restrictive-umask")
        self.assertEqual((code, report["outcome"]), (0, "confirmed"), report)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o755)

    def test_complete_prepared_copy_is_rechecked_before_publication(self) -> None:
        code, report = self.export(fault="late-stage-corruption")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["outcome"], "not-published")
        self.assertFalse(self.output.exists())
