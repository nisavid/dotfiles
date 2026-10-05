"""Offline recovery through the public command in disposable homes."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tests.provingkit_fixtures import fixture_recovery_packet

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / "home/private_dot_local/bin/executable_provingkit-installations"


class RecoveryCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.selection_path = self.base / "selection.json"
        self.selection = {
            "schema": "provingkit-installations-v1",
            "profile_name": None,
            "profile": None,
            "host_platform": {"os": "linux", "arch": "amd64"},
            "recovery_packets": {},
        }
        self.environment = {
            "HOME": str(self.home),
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
        }

    def run_command(self, *arguments):
        self.selection_path.write_text(json.dumps(self.selection))
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(COMMAND),
                *arguments,
                "--selection",
                str(self.selection_path),
                "--json",
            ],
            cwd=self.home,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertTrue(result.stdout, result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_unknown_recovery_is_refused_without_materialization(self):
        code, report = self.run_command(
            "import-artifacts",
            "--recovery",
            "missing",
            "--packet",
            str(self.base / "missing.tar.gz"),
        )

        self.assertEqual((code, report["outcome"]), (64, "invalid_selection"))
        self.assertIn("unknown recovery", report["message"])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_validate_refuses_malformed_recovery_metadata_while_inactive(self):
        self.selection, _packet, _manifest = fixture_recovery_packet(self.base)
        self.selection["recovery_packets"]["fixture"]["schema"] = "untrusted"

        code, report = self.run_command("validate")

        self.assertEqual((code, report["outcome"]), (64, "invalid_selection"))
        self.assertIn("recovery", report["message"])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_verified_packet_imports_canonical_artifacts_and_parent_bound_alias(self):
        self.selection, packet, manifest = fixture_recovery_packet(self.base)

        code, report = self.run_command(
            "import-artifacts", "--recovery", "fixture", "--packet", str(packet)
        )

        self.assertEqual((code, report["outcome"]), (0, "artifacts_imported"), report)
        self.assertEqual(report["clients"], {})
        self.assertEqual(
            set(report["targets"]), {"agent-plugins", "agent-plugins-local", "claude"}
        )
        data_root = self.home / ".local/share/provingkit"
        for target, specification in manifest["targets"].items():
            artifact = (
                data_root / "artifacts" / target / specification["artifact_sha256"]
            )
            evidence = (
                data_root / "evidence" / target / specification["artifact_sha256"]
            )
            self.assertEqual(artifact.stat().st_mode & 0o777, 0o700)
            self.assertEqual((artifact / "RECEIPT.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                (artifact / "RECEIPT.json").read_bytes(),
                (evidence / "RECEIPT.json").read_bytes(),
            )
            self.assertEqual(
                {p.name for p in evidence.iterdir()}, {"RECEIPT.json", "modes.tsv"}
            )
            catalog = json.loads((artifact / specification["catalog"]).read_text())
            self.assertEqual(
                catalog["name"],
                "provingkit-local" if target == "agent-plugins-local" else "provingkit",
            )
            self.assertEqual(
                [row["name"] for row in catalog["plugins"]], manifest["artifact_slate"]
            )
        self.assertFalse((self.home / ".config").exists())
        self.assertFalse((self.home / ".local/state").exists())
        self.assertFalse((self.home / ".cache").exists())

    def test_conflicting_destination_preserves_it_and_publishes_nothing(self):
        self.selection, packet, manifest = fixture_recovery_packet(self.base)
        destination = (
            self.home
            / ".local/share/provingkit/artifacts/claude"
            / manifest["targets"]["claude"]["artifact_sha256"]
        )
        destination.mkdir(parents=True)
        sentinel = destination / "keep.txt"
        sentinel.write_text("existing operator content\n")

        code, report = self.run_command(
            "import-artifacts", "--recovery", "fixture", "--packet", str(packet)
        )

        self.assertFalse(
            (self.home / ".local/share/provingkit/artifacts/agent-plugins").exists()
        )
        self.assertEqual((code, report["outcome"]), (1, "recovery_refused"), report)
        self.assertEqual(sentinel.read_text(), "existing operator content\n")
        self.assertFalse((self.home / ".local/share/provingkit/evidence").exists())

    def test_repeat_import_verifies_existing_artifacts_without_changing_them(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        arguments = (
            "import-artifacts",
            "--recovery",
            "fixture",
            "--packet",
            str(packet),
        )
        code, report = self.run_command(*arguments)
        self.assertEqual(code, 0, report)
        before = {
            p.relative_to(self.home).as_posix(): (
                p.lstat().st_mode,
                p.lstat().st_mtime_ns,
                p.read_bytes() if p.is_file() else None,
            )
            for p in self.home.rglob("*")
        }

        code, report = self.run_command(*arguments)

        self.assertEqual((code, report["outcome"]), (0, "artifacts_verified"), report)
        self.assertTrue(
            all(row["outcome"] == "verified" for row in report["targets"].values())
        )
        self.assertEqual(
            before,
            {
                p.relative_to(self.home).as_posix(): (
                    p.lstat().st_mode,
                    p.lstat().st_mtime_ns,
                    p.read_bytes() if p.is_file() else None,
                )
                for p in self.home.rglob("*")
            },
        )

    def packet_contents(self, packet):
        with tarfile.open(packet) as archive:
            return {item.name: archive.extractfile(item).read() for item in archive}

    def write_packet(self, packet, contents):
        with tarfile.open(packet, "w:gz") as archive:
            for name, data in sorted(contents.items()):
                item = tarfile.TarInfo(name)
                item.size, item.mode = len(data), 0o600
                archive.addfile(item, io.BytesIO(data))
        record = self.selection["recovery_packets"]["fixture"]
        record["packet"] = {
            "bytes": packet.stat().st_size,
            "sha256": hashlib.sha256(packet.read_bytes()).hexdigest(),
        }
        record["manifest_sha256"] = hashlib.sha256(
            contents["MANIFEST.json"]
        ).hexdigest()

    def test_duplicate_manifest_fields_are_refused_as_invalid_recovery(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        contents = self.packet_contents(packet)
        contents["MANIFEST.json"] = contents["MANIFEST.json"].replace(
            b"{", b'{"schema":"duplicate",', 1
        )
        self.write_packet(packet, contents)

        code, report = self.run_command(
            "import-artifacts", "--recovery", "fixture", "--packet", str(packet)
        )

        self.assertEqual((code, report["outcome"]), (1, "recovery_invalid"), report)
        self.assertIn("duplicate", report["message"])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_missing_host_platform_is_reported_as_invalid_selection(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        del self.selection["host_platform"]

        code, report = self.run_command(
            "import-artifacts", "--recovery", "fixture", "--packet", str(packet)
        )

        self.assertEqual((code, report["outcome"]), (64, "invalid_selection"), report)
        self.assertEqual(list(self.home.iterdir()), [])

    def replace_constituent(self, packet, path, data):
        contents = self.packet_contents(packet)
        manifest = json.loads(contents["MANIFEST.json"])
        contents[path] = data
        sha = hashlib.sha256(data).hexdigest()
        for item in manifest["files"]:
            if item["path"] == path:
                item.update(bytes=len(data), sha256=sha)
        for specification in manifest["targets"].values():
            for kind in ("archive", "receipt", "modes"):
                if specification[kind]["path"] == path:
                    specification[kind]["sha256"] = sha
        contents["MANIFEST.json"] = (json.dumps(manifest) + "\n").encode()
        self.write_packet(packet, contents)

    def import_fixture(self, packet):
        return self.run_command(
            "import-artifacts", "--recovery", "fixture", "--packet", str(packet)
        )

    def test_missing_or_changed_packet_does_not_materialize_artifacts(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        expected = packet.read_bytes()
        for condition in ("missing", "size", "digest"):
            with self.subTest(condition=condition):
                if condition == "missing":
                    packet.unlink(missing_ok=True)
                elif condition == "size":
                    packet.write_bytes(expected[:-1])
                else:
                    packet.write_bytes(expected[:-1] + bytes([expected[-1] ^ 1]))
                code, report = self.import_fixture(packet)
                self.assertEqual(
                    (code, report["outcome"]), (1, "recovery_invalid"), report
                )
                self.assertEqual(list(self.home.iterdir()), [])

    def test_manifest_is_authenticated_before_its_json_is_used(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        contents = self.packet_contents(packet)
        original_pin = self.selection["recovery_packets"]["fixture"]["manifest_sha256"]
        contents["MANIFEST.json"] = b"not JSON"
        self.write_packet(packet, contents)
        self.selection["recovery_packets"]["fixture"]["manifest_sha256"] = original_pin

        code, report = self.import_fixture(packet)

        self.assertEqual((code, report["outcome"]), (1, "recovery_invalid"), report)
        self.assertIn("manifest digest differs", report["message"])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_unsupported_platform_is_refused_before_reading_packet(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        self.selection["recovery_packets"]["fixture"]["platform"] = {
            "os": "linux",
            "arch": "arm64",
        }
        self.selection["host_platform"] = {"os": "linux", "arch": "arm64"}
        packet.unlink()

        code, report = self.import_fixture(packet)

        self.assertEqual((code, report["outcome"]), (2, "unsupported_platform"), report)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_symlink_destination_ancestor_is_preserved_and_refused(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        outside = self.base / "outside"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("outside content\n")
        (self.home / ".local").symlink_to(outside, target_is_directory=True)

        code, report = self.import_fixture(packet)

        self.assertEqual((code, report["outcome"]), (1, "recovery_refused"), report)
        self.assertTrue((self.home / ".local").is_symlink())
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), "outside content\n")

    def test_repeat_import_refuses_changed_receipt_mode_or_extra_evidence(self):
        self.selection, packet, manifest = fixture_recovery_packet(self.base)
        code, report = self.import_fixture(packet)
        self.assertEqual(code, 0, report)
        tree = manifest["targets"]["claude"]["artifact_sha256"]
        artifact = self.home / ".local/share/provingkit/artifacts/claude" / tree
        evidence = self.home / ".local/share/provingkit/evidence/claude" / tree
        receipt = artifact / "RECEIPT.json"
        receipt.chmod(0o644)

        code, report = self.import_fixture(packet)

        self.assertEqual((code, report["outcome"]), (1, "recovery_refused"), report)
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o644)
        receipt.chmod(0o600)
        extra = evidence / "operator.txt"
        extra.write_text("keep extra evidence\n")
        code, report = self.import_fixture(packet)
        self.assertEqual((code, report["outcome"]), (1, "recovery_refused"), report)
        self.assertEqual(extra.read_text(), "keep extra evidence\n")

    def test_missing_evidence_can_be_recovered_without_replacing_matching_artifacts(
        self,
    ):
        self.selection, packet, manifest = fixture_recovery_packet(self.base)
        code, report = self.import_fixture(packet)
        self.assertEqual(code, 0, report)
        tree = manifest["targets"]["claude"]["artifact_sha256"]
        artifact = self.home / ".local/share/provingkit/artifacts/claude" / tree
        before = (artifact / "RECEIPT.json").stat().st_mtime_ns
        evidence = self.home / ".local/share/provingkit/evidence/claude" / tree
        shutil.rmtree(evidence)

        code, report = self.import_fixture(packet)

        self.assertEqual((code, report["outcome"]), (0, "artifacts_imported"), report)
        self.assertEqual(report["targets"]["claude"]["outcome"], "imported")
        self.assertEqual(report["targets"]["agent-plugins"]["outcome"], "verified")
        self.assertEqual((artifact / "RECEIPT.json").stat().st_mtime_ns, before)
        self.assertTrue((evidence / "modes.tsv").is_file())

    def test_import_does_not_inspect_profile_or_invoke_native_clients(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        self.selection["profile_name"] = "unrelated-profile"
        self.selection["profile"] = {"unsupported": "not recovery metadata"}
        binary = self.base / "bin"
        binary.mkdir()
        marker = self.base / "client-called"
        for client in ("codex", "claude", "cursor"):
            path = binary / client
            path.write_text(
                '#!/bin/sh\nprintf called > "' + str(marker) + '"\nexit 99\n'
            )
            path.chmod(0o755)
        self.environment["PATH"] = str(binary) + ":/usr/bin:/bin"

        code, report = self.import_fixture(packet)

        self.assertEqual((code, report["outcome"]), (0, "artifacts_imported"), report)
        self.assertFalse(marker.exists())
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse((self.home / ".claude").exists())
        self.assertFalse((self.home / ".cursor").exists())

    def rewrite_archive(self, raw, change):
        members = []
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for item in archive:
                members.append(
                    (
                        deepcopy(item),
                        archive.extractfile(item).read() if item.isreg() else None,
                    )
                )
        change(members)
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for item, data in members:
                archive.addfile(item, io.BytesIO(data) if data is not None else None)
        return stream.getvalue()

    def test_unsafe_archive_entries_are_refused_before_any_materialization(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        path = "artifacts/agent-plugins.tar.gz"
        original = self.packet_contents(packet)[path]
        for condition in (
            "unsafe",
            "duplicate",
            "symlink",
            "hardlink",
            "special",
            "conflicting-ancestry",
            "unsupported-pax",
        ):
            with self.subTest(condition=condition):

                def change(members, condition=condition):
                    item = tarfile.TarInfo("agent-plugins/unexpected")
                    item.mode = 0o600
                    data = b"bad entry\n"
                    item.size = len(data)
                    if condition == "unsafe":
                        item.name = "agent-plugins/../escape"
                    elif condition == "duplicate":
                        members.append(deepcopy(members[0]))
                        return
                    elif condition in ("symlink", "hardlink"):
                        item.type = (
                            tarfile.SYMTYPE
                            if condition == "symlink"
                            else tarfile.LNKTYPE
                        )
                        item.linkname = "../../outside"
                        item.size, data = 0, None
                    elif condition == "special":
                        item.type, item.size, data = tarfile.FIFOTYPE, 0, None
                    elif condition == "conflicting-ancestry":
                        child = tarfile.TarInfo(item.name + "/child")
                        child.mode, child.size = 0o600, len(data)
                        members.append((child, data))
                    elif condition == "unsupported-pax":
                        members[0][0].pax_headers = {"mtime": "1"}
                        return
                    members.append((item, data))

                archive = self.rewrite_archive(original, change)
                self.replace_constituent(packet, path, archive)

                code, report = self.import_fixture(packet)

                self.assertEqual(
                    (code, report["outcome"]), (1, "recovery_invalid"), report
                )
                self.assertEqual(list(self.home.iterdir()), [])

    def test_path_pax_header_and_conventional_directory_slash_are_supported(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        path = "artifacts/agent-plugins.tar.gz"
        original = self.packet_contents(packet)[path]

        def change(members):
            for item, _data in members:
                if item.isdir():
                    item.name += "/"
            item = next(item for item, _data in members if item.isreg())
            effective = item.name
            item.name = "placeholder"
            item.pax_headers = {"path": effective}

        self.replace_constituent(packet, path, self.rewrite_archive(original, change))

        code, report = self.import_fixture(packet)

        self.assertEqual((code, report["outcome"]), (0, "artifacts_imported"), report)

    def test_artifact_directory_receipt_and_alias_file_modes_are_verified(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        originals = self.packet_contents(packet)
        for target, suffix in (
            ("agent-plugins", "/.agents"),
            ("claude", "/RECEIPT.json"),
            ("agent-plugins-local", "/.agents/plugins/marketplace.json"),
        ):
            with self.subTest(target=target, path=suffix):
                path = f"artifacts/{target}.tar.gz"

                def change(members, target=target, suffix=suffix):
                    item = next(
                        item for item, _data in members if item.name == target + suffix
                    )
                    item.mode = (
                        0o755
                        if item.isdir()
                        else 0o644 if item.mode != 0o644 else 0o600
                    )

                self.replace_constituent(
                    packet, path, self.rewrite_archive(originals[path], change)
                )

                code, report = self.import_fixture(packet)

                self.assertEqual(
                    (code, report["outcome"]), (1, "recovery_invalid"), report
                )
                self.assertEqual(list(self.home.iterdir()), [])
                self.replace_constituent(packet, path, originals[path])

    def test_alias_receipt_must_bind_the_canonical_parent_receipt(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        contents = self.packet_contents(packet)
        receipt = json.loads(contents["receipts/agent-plugins-local.json"])
        receipt["parent_receipt_sha256"] = "0" * 64
        altered = (json.dumps(receipt, indent=2) + "\n").encode()
        archive_path = "artifacts/agent-plugins-local.tar.gz"

        def change(members):
            for index, (item, _data) in enumerate(members):
                if item.name == "agent-plugins-local/RECEIPT.json":
                    item.size = len(altered)
                    members[index] = item, altered

        self.replace_constituent(
            packet, archive_path, self.rewrite_archive(contents[archive_path], change)
        )
        self.replace_constituent(packet, "receipts/agent-plugins-local.json", altered)

        code, report = self.import_fixture(packet)

        self.assertEqual((code, report["outcome"]), (1, "recovery_invalid"), report)
        self.assertIn("not parent-bound", report["message"])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_alias_directory_inventory_must_match_the_canonical_parent(self):
        self.selection, packet, _manifest = fixture_recovery_packet(self.base)
        contents = self.packet_contents(packet)
        archive_path = "artifacts/agent-plugins-local.tar.gz"

        def change(members):
            directory = tarfile.TarInfo("agent-plugins-local/extra-empty")
            directory.type, directory.mode = tarfile.DIRTYPE, 0o700
            members.append((directory, None))

        self.replace_constituent(
            packet,
            archive_path,
            self.rewrite_archive(contents[archive_path], change),
        )
        contents = self.packet_contents(packet)
        manifest = json.loads(contents["MANIFEST.json"])
        manifest["targets"]["agent-plugins-local"]["directories"][
            "extra-empty"
        ] = "0700"
        contents["MANIFEST.json"] = (json.dumps(manifest) + "\n").encode()
        self.write_packet(packet, contents)

        code, report = self.import_fixture(packet)

        self.assertEqual((code, report["outcome"]), (1, "recovery_invalid"), report)
        self.assertIn("alias directory", report["message"])
        self.assertEqual(list(self.home.iterdir()), [])
