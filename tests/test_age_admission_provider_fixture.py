from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tarfile
import textwrap
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tests.age_tooling_test_support import require_age_tooling_or_skip

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts/build-age-admission-provider-fixture"
SOURCE_MODES = {
    "home/private_dot_local/bin/executable_proton-pass-age-admission": "100644",
    "home/private_dot_local/bin/executable_proton-pass-ensure-ready": "100755",
    "scripts/admit-age-envelopes": "100755",
    "scripts/agent_equipment_public_data.py": "100644",
    "scripts/build-age-admission-provider-fixture": "100755",
    "scripts/create-age-admission-receipt": "100755",
    "scripts/prepare-age-admission-recovery-preimage": "100755",
    "scripts/privacy-scan": "100755",
    "scripts/privacy_age_admission.py": "100644",
    "scripts/privacy_age_envelopes.py": "100644",
    "scripts/privacy_age_integrity_gate.py": "100755",
    "scripts/provision-age-admission-signer": "100755",
    "scripts/run-trusted-age-admission": "100755",
}
NON_PROVIDER_SUPPORT = frozenset({"git", "ssh-keygen"})


def resolved_non_provider_support(name: str) -> Path:
    if name not in NON_PROVIDER_SUPPORT:
        raise AssertionError(f"unsupported test command: {name}")
    command = shutil.which(name)
    if command is None:
        raise unittest.SkipTest(f"required test support command is unavailable: {name}")
    return Path(command).resolve(strict=True)


def selected_age_tooling_archive_or_skip() -> tuple[Path, str]:
    raw_archive = os.environ.get("AGE_TOOLING_ARCHIVE")
    expected_digest = os.environ.get("AGE_TOOLING_ARCHIVE_SHA256")
    message = (
        "set AGE_TOOLING_ARCHIVE and AGE_TOOLING_ARCHIVE_SHA256 to one "
        "checksum-pinned age archive for this runner"
    )
    if not raw_archive or not expected_digest:
        require_age_tooling_or_skip(message)
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdef" for character in expected_digest
    ):
        require_age_tooling_or_skip("AGE_TOOLING_ARCHIVE_SHA256 is invalid")
    archive = Path(raw_archive)
    if not archive.is_absolute():
        require_age_tooling_or_skip("AGE_TOOLING_ARCHIVE must be absolute")
    try:
        archive_data = archive.read_bytes()
    except OSError as error:
        require_age_tooling_or_skip(
            "the selected age tooling archive is unavailable", cause=error
        )
    if sha256(archive_data) != expected_digest:
        require_age_tooling_or_skip(
            "the selected age tooling archive checksum is invalid"
        )
    return archive, expected_digest


def canonical_json(document: object) -> bytes:
    return (
        json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    environment = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": os.fspath(repository.parent),
        "LC_ALL": "C",
        "PATH": "",
    }
    return subprocess.run(
        [
            os.fspath(resolved_non_provider_support("git")),
            "-c",
            "protocol.allow=never",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-C",
            os.fspath(repository),
            *arguments,
        ],
        check=True,
        capture_output=True,
        env=environment,
        timeout=20,
    )


class FixtureInputs:
    def __init__(self, root: Path, *, real_launcher: bool = False) -> None:
        self.root = root
        self.real_launcher = real_launcher
        self.source = root / "reviewed-source"
        self.source.mkdir(mode=0o700)
        self.archive = root / "age-v1.3.1-synthetic.tar.gz"
        self.manifest = root / "reviewed-source-manifest.json"
        self.signer_public_key = root / "signer.pub"
        self.request = root / "request.json"
        self.operations = root / "operations"
        self.operations.mkdir(mode=0o700)
        self.operation = self.operations / "fixture"
        self.provider_marker = root / "provider-accessed"
        self.network_marker = root / "network-accessed"

        self._write_fake_age_archive()
        self._write_source_repository()
        self._write_signer_public_key()
        self._write_request()

    @staticmethod
    def trusted_launcher_stub() -> bytes:
        body = textwrap.dedent(
            """\
            import os
            import stat
            import sys

            arguments = sys.argv[1:]
            required = (
                "--base-repository",
                "--base-commit",
                "--",
                "--operation",
                "preflight",
                "--head-repository",
                "--head-commit",
            )
            if (
                stat.S_IMODE(os.stat(__file__).st_mode) == 0o755
                and sys.flags.isolated
                and sys.flags.dont_write_bytecode
                and sys.flags.no_site
                and all(value in arguments for value in required)
            ):
                print("required")
                raise SystemExit(0)
            raise SystemExit(97)
            """
        ).encode("ascii")
        return f"#!{sys.executable} -B\n".encode() + body

    @staticmethod
    def peer_stub(name: str) -> bytes:
        return (
            f"#!{sys.executable} -B\n"
            f'"""Synthetic reviewed-source stub for {name}."""\n'
            "raise SystemExit(0)\n"
        ).encode("ascii")

    @staticmethod
    def fake_age_tool() -> bytes:
        body = textwrap.dedent(
            """\
            import base64
            import json
            import os
            import sys

            name = os.path.basename(sys.argv[0])
            arguments = sys.argv[1:]
            if arguments == ["--version"]:
                print("v1.3.1")
                raise SystemExit(0)
            if name == "age-keygen" and arguments == ["-pq"]:
                print("# public key: age1pq1syntheticfixtureonly")
                identity = "AGE-" + "SECRET-KEY-PQ-1SYNTHETICFIXTUREONLY"
                print(identity)
                raise SystemExit(0)
            if name == "age-keygen" and arguments[:1] == ["-y"]:
                print("age1pq1syntheticfixtureonly")
                raise SystemExit(0)
            if name == "age-inspect" and arguments == ["--json", "-"]:
                data = sys.stdin.buffer.read()
                if not data.startswith(b"age-encryption.org/v1\\n"):
                    raise SystemExit(1)
                print(json.dumps({
                    "version": "age-encryption.org/v1",
                    "postquantum": "yes",
                    "armor": False,
                    "stanza_types": ["mlkem768x25519"],
                    "sizes": {
                        "header": 24,
                        "armor": 0,
                        "overhead": 0,
                        "min_payload": 1,
                        "max_payload": 64,
                        "min_padding": 0,
                        "max_padding": 0,
                    },
                }))
                raise SystemExit(0)
            if name == "age" and "--decrypt" in arguments:
                data = sys.stdin.buffer.read()
                prefix = b"age-encryption.org/v1\\n"
                if not data.startswith(prefix):
                    raise SystemExit(1)
                sys.stdout.buffer.write(base64.b64decode(data[len(prefix):]))
                raise SystemExit(0)
            if name == "age" and "--recipient" in arguments:
                plaintext = sys.stdin.buffer.read()
                sys.stdout.buffer.write(
                    b"age-encryption.org/v1\\n" + base64.b64encode(plaintext)
                )
                raise SystemExit(0)
            raise SystemExit(96)
            """
        ).encode("ascii")
        return f"#!{sys.executable} -B\n".encode() + body

    def _write_fake_age_archive(self, tool: bytes | None = None) -> None:
        tool = tool or self.fake_age_tool()
        with tarfile.open(self.archive, "w:gz") as archive:
            for name in ("age", "age-inspect", "age-keygen"):
                info = tarfile.TarInfo(f"age/{name}")
                info.mode = 0o755
                info.size = len(tool)
                info.mtime = 0
                archive.addfile(info, io.BytesIO(tool))
        self.archive.chmod(0o600)

    def replace_age_archive(self, tool: bytes) -> None:
        self._write_fake_age_archive(tool)
        self.request_document["age_tooling"]["sha256"] = sha256(
            self.archive.read_bytes()
        )
        self.request.write_bytes(canonical_json(self.request_document))
        self.request.chmod(0o600)

    def _source_bytes(self, relative: str) -> bytes:
        if relative == "scripts/run-trusted-age-admission" and not self.real_launcher:
            return self.trusted_launcher_stub()
        if relative in {
            "scripts/prepare-age-admission-recovery-preimage",
            "scripts/provision-age-admission-signer",
        }:
            return self.peer_stub(relative)
        return (ROOT / relative).read_bytes()

    def _write_source_repository(self) -> None:
        run_git(self.source, "init", "--quiet")
        for relative, mode in SOURCE_MODES.items():
            destination = self.source / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.write_bytes(self._source_bytes(relative))
            destination.chmod(0o755 if mode == "100755" else 0o644)
        run_git(self.source, "add", "--all")
        run_git(
            self.source,
            "-c",
            "user.name=Synthetic Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "synthetic reviewed source",
        )
        self.commit = run_git(self.source, "rev-parse", "HEAD").stdout.decode().strip()
        entries = []
        for relative in sorted(SOURCE_MODES):
            record = run_git(
                self.source,
                "ls-tree",
                self.commit,
                "--",
                relative,
            ).stdout.decode("ascii")
            mode, kind, object_and_path = record.split(maxsplit=2)
            object_id, path = object_and_path.rstrip("\n").split("\t", 1)
            self.assert_source_record(relative, mode, kind, path)
            blob = run_git(self.source, "cat-file", "blob", object_id).stdout
            entries.append({"mode": mode, "path": relative, "sha256": sha256(blob)})
        self.manifest_document = {
            "commit": self.commit,
            "entries": entries,
            "schema": "issue286-reviewed-source-manifest/v1",
        }
        self.manifest.write_bytes(canonical_json(self.manifest_document))
        self.manifest.chmod(0o600)

    @staticmethod
    def assert_source_record(
        relative: str,
        mode: str,
        kind: str,
        path: str,
    ) -> None:
        if (mode, kind, path) != (SOURCE_MODES[relative], "blob", relative):
            raise AssertionError((relative, mode, kind, path))

    def _write_signer_public_key(self) -> None:
        algorithm = b"ssh-ed25519"
        key = bytes(range(32))
        blob = (
            struct.pack(">I", len(algorithm))
            + algorithm
            + struct.pack(">I", len(key))
            + key
        )
        encoded = base64.b64encode(blob).decode("ascii")
        self.signer_public_key.write_text(
            f"ssh-ed25519 {encoded} synthetic@example.invalid\n",
            encoding="ascii",
        )
        self.signer_public_key.chmod(0o600)

    def _write_request(self, **updates: object) -> None:
        self.request_document = {
            "age_tooling": {
                "archive": os.fspath(self.archive),
                "sha256": sha256(self.archive.read_bytes()),
            },
            "reviewed_source": {
                "commit": self.commit,
                "manifest": {
                    "path": os.fspath(self.manifest),
                    "sha256": sha256(self.manifest.read_bytes()),
                },
                "repository": os.fspath(self.source),
            },
            "schema": "issue286-provider-fixture/v1",
            "signer_public_key": os.fspath(self.signer_public_key),
        }
        self.request_document.update(updates)
        self.request.write_bytes(canonical_json(self.request_document))
        self.request.chmod(0o600)

    def rewrite_manifest_and_request(self) -> None:
        self.manifest.write_bytes(canonical_json(self.manifest_document))
        self.manifest.chmod(0o600)
        manifest = self.request_document["reviewed_source"]["manifest"]
        manifest["sha256"] = sha256(self.manifest.read_bytes())
        self.request_document["reviewed_source"]["commit"] = self.manifest_document[
            "commit"
        ]
        self.request.write_bytes(canonical_json(self.request_document))
        self.request.chmod(0o600)

    def replace_reviewed_source(self, relative: str, data: bytes) -> None:
        path = self.source / relative
        path.write_bytes(data)
        path.chmod(0o755 if SOURCE_MODES[relative] == "100755" else 0o644)
        run_git(self.source, "add", "--", relative)
        run_git(
            self.source,
            "-c",
            "user.name=Synthetic Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            f"replace synthetic reviewed {relative}",
        )
        self.commit = run_git(self.source, "rev-parse", "HEAD").stdout.decode().strip()
        self.manifest_document["commit"] = self.commit
        entry = next(
            entry
            for entry in self.manifest_document["entries"]
            if entry["path"] == relative
        )
        entry["sha256"] = sha256(data)
        self.rewrite_manifest_and_request()

    def builder_environment(self) -> dict[str, str]:
        fake_path = self.root / "ambient-tools"
        fake_path.mkdir(mode=0o700, exist_ok=True)
        for name, marker in (
            ("pass-cli", self.provider_marker),
            ("gh", self.network_marker),
            ("curl", self.network_marker),
        ):
            executable = fake_path / name
            executable.write_text(
                f"#!/bin/sh\nprintf accessed > {os.fspath(marker)!r}\nexit 98\n",
                encoding="ascii",
            )
            executable.chmod(0o700)
        support_path = self.root / "support-tools"
        support_path.mkdir(mode=0o700, exist_ok=True)
        git = support_path / "git"
        if not git.exists():
            git.symlink_to(resolved_non_provider_support("git"))
        home = self.root / "home"
        home.mkdir(mode=0o700, exist_ok=True)
        return {
            "HOME": os.fspath(home),
            "LC_ALL": "C",
            "PATH": os.pathsep.join((os.fspath(fake_path), os.fspath(support_path))),
            "PYTHONPYCACHEPREFIX": os.fspath(self.root / "pycache"),
            "TEMP": os.fspath(self.root),
            "TMP": os.fspath(self.root),
            "TMPDIR": os.fspath(self.root),
        }

    def builder_command(self, executable: Path = BUILDER) -> list[str]:
        return [
            sys.executable,
            "-I",
            "-B",
            "-S",
            os.fspath(executable),
            "--request",
            os.fspath(self.request),
            "--operation-directory",
            os.fspath(self.operation),
        ]

    def run_builder(
        self, executable: Path = BUILDER
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            self.builder_command(executable),
            check=False,
            capture_output=True,
            env=self.builder_environment(),
            timeout=40,
            umask=0o022,
        )


class AgeToolingSelectionTests(unittest.TestCase):
    def test_optional_local_run_skips_without_selected_archive(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(
                unittest.SkipTest,
                "set AGE_TOOLING_ARCHIVE and AGE_TOOLING_ARCHIVE_SHA256",
            ),
        ):
            selected_age_tooling_archive_or_skip()

    def test_required_run_fails_when_selected_archive_is_absent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            environment = {
                "AGE_TOOLING_ARCHIVE": os.fspath(root / "missing.tar.gz"),
                "AGE_TOOLING_ARCHIVE_SHA256": "0" * 64,
                "REQUIRE_AGE_TOOLING": "1",
            }
            with (
                mock.patch.dict(os.environ, environment, clear=True),
                self.assertRaisesRegex(
                    AssertionError,
                    "selected age tooling archive is unavailable",
                ),
            ):
                selected_age_tooling_archive_or_skip()

    def test_required_run_fails_when_selected_archive_checksum_is_invalid(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            archive = root / "age.tar.gz"
            archive.write_bytes(b"synthetic test archive\n")
            environment = {
                "AGE_TOOLING_ARCHIVE": os.fspath(archive),
                "AGE_TOOLING_ARCHIVE_SHA256": sha256(b"different archive\n"),
                "REQUIRE_AGE_TOOLING": "1",
            }
            with (
                mock.patch.dict(os.environ, environment, clear=True),
                self.assertRaisesRegex(
                    AssertionError,
                    "selected age tooling archive checksum is invalid",
                ),
            ):
                selected_age_tooling_archive_or_skip()

    def test_required_run_accepts_explicit_checksum_bound_archive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            archive = root / "age.tar.gz"
            archive_data = b"synthetic test archive\n"
            archive.write_bytes(archive_data)
            environment = {
                "AGE_TOOLING_ARCHIVE": os.fspath(archive),
                "AGE_TOOLING_ARCHIVE_SHA256": sha256(archive_data),
                "REQUIRE_AGE_TOOLING": "1",
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                self.assertEqual(
                    selected_age_tooling_archive_or_skip(),
                    (archive, sha256(archive_data)),
                )


class AgeAdmissionProviderFixtureTests(unittest.TestCase):
    def make_inputs(
        self,
        *,
        real_launcher: bool = False,
        temporary_parent: Path | None = None,
    ) -> tuple[TemporaryDirectory[str], FixtureInputs]:
        temporary = TemporaryDirectory(
            prefix="age-admission-provider-fixture.", dir=temporary_parent
        )
        root = Path(temporary.name).resolve(strict=True)
        root.chmod(0o700)
        return temporary, FixtureInputs(root, real_launcher=real_launcher)

    @staticmethod
    def trusted_path_ancestors_supported(path: Path) -> bool:
        owner = os.geteuid()
        current = path
        while True:
            info = current.lstat()
            writable = bool(info.st_mode & 0o022)
            root_owned_sticky = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid not in {0, owner}
                or writable
                and not root_owned_sticky
            ):
                return False
            parent = current.parent
            if parent == current:
                return True
            current = parent

    @staticmethod
    def configure_slow_age_child(inputs: FixtureInputs, marker: Path) -> None:
        slow_body = textwrap.dedent(
            f"""\
            import os
            import sys
            import time

            name = os.path.basename(sys.argv[0])
            arguments = sys.argv[1:]
            if arguments == ["--version"]:
                print("v1.3.1")
                raise SystemExit(0)
            if name == "age-keygen" and arguments == ["-pq"]:
                with open({os.fspath(marker)!r}, "w", encoding="ascii") as stream:
                    stream.write(str(os.getpid()))
                    stream.flush()
                time.sleep(60)
                raise SystemExit(99)
            raise SystemExit(96)
            """
        ).encode("ascii")
        inputs.replace_age_archive(f"#!{sys.executable} -B\n".encode() + slow_body)

    def _run_with_group_probe_fault(
        self,
        inputs: FixtureInputs,
        *,
        persistent: bool,
        until_reaped: bool = False,
    ) -> tuple[tuple[int, bytes, bytes], int]:
        child_marker = inputs.root / (
            "persistent-probe-child" if persistent else "transient-probe-child"
        )
        fault_marker = inputs.root / (
            "zombie-only-group-probe-fault"
            if until_reaped
            else (
                "persistent-group-probe-fault"
                if persistent
                else "transient-group-probe-fault"
            )
        )
        self.configure_slow_age_child(inputs, child_marker)
        harness = textwrap.dedent(
            f"""\
            import errno
            import os
            import pathlib
            import runpy
            import signal
            import subprocess
            import sys

            real_killpg = os.killpg
            real_poll = subprocess.Popen.poll
            armed = False
            faulted = False
            reap_deferred_groups = set()
            reaped_groups = set()

            def faulting_killpg(process_group, signum):
                global armed, faulted
                if signum == 0 and armed and (
                    {persistent!r}
                    or ({until_reaped!r} and process_group not in reaped_groups)
                    or (not {until_reaped!r} and not faulted)
                ):
                    faulted = True
                    pathlib.Path({os.fspath(fault_marker)!r}).write_text(
                        str(process_group), encoding="ascii"
                    )
                    raise PermissionError(
                        errno.EPERM, "synthetic group probe uncertainty"
                    )
                result = real_killpg(process_group, signum)
                if signum == signal.SIGTERM:
                    armed = True
                return result

            def observing_poll(process):
                if (
                    {until_reaped!r}
                    and armed
                    and process.pid not in reap_deferred_groups
                ):
                    reap_deferred_groups.add(process.pid)
                    return None
                result = real_poll(process)
                if result is not None:
                    reaped_groups.add(process.pid)
                return result

            os.killpg = faulting_killpg
            subprocess.Popen.poll = observing_poll
            source = sys.argv[1]
            sys.argv = [source, *sys.argv[2:]]
            runpy.run_path(source, run_name="__main__")
            """
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                "-c",
                harness,
                os.fspath(BUILDER),
                *inputs.builder_command()[5:],
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=inputs.builder_environment(),
            start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while not child_marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(child_marker.exists(), "slow age child did not start")

        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)

        self.assertTrue(fault_marker.exists(), "group probe fault was not injected")
        process_group = int(fault_marker.read_text(encoding="ascii"))
        assert process.returncode is not None
        return (process.returncode, stdout, stderr), process_group

    def test_builds_bound_provider_free_synthetic_fixture(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)

        result = inputs.run_builder()

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, b"fixture-ready\n", b""),
        )
        self.assertFalse(inputs.provider_marker.exists())
        self.assertFalse(inputs.network_marker.exists())
        fixture_path = inputs.operation / "fixture.json"
        self.assertEqual(stat.S_IMODE(fixture_path.stat().st_mode), 0o600)
        fixture_bytes = fixture_path.read_bytes()
        fixture = json.loads(fixture_bytes)
        self.assertEqual(fixture_bytes, canonical_json(fixture))
        self.assertEqual(fixture["schema"], "issue286-provider-fixture-binding/v1")
        self.assertEqual(
            fixture["authority"],
            {
                "publication_permitted": False,
                "purpose": "offline-synthetic-provider-qualification",
                "real_transition_authority": False,
                "repository": "fixture.invalid/issue286-age-admission-provider",
            },
        )
        self.assertEqual(
            fixture["preflight"],
            {"status": 0, "stderr_utf8": "", "stdout_utf8": "required\n"},
        )
        self.assertEqual(fixture["source"]["commit"], inputs.commit)
        self.assertEqual(
            fixture["source"]["manifest_sha256"],
            sha256(inputs.manifest.read_bytes()),
        )
        identity = inputs.operation / fixture["age_identity"]["path"]
        self.assertEqual(stat.S_IMODE(identity.stat().st_mode), 0o600)
        self.assertEqual(
            sha256(identity.read_bytes()), fixture["age_identity"]["sha256"]
        )
        self.assertNotIn(b"AGE-SECRET-KEY", fixture_bytes)
        for directory in (
            inputs.operation,
            inputs.operation / "private",
            inputs.operation / "repositories",
            inputs.operation / "tools",
        ):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for binding in fixture["staged_tools"].values():
            tool = inputs.operation / binding["path"]
            expected_mode = (
                0o755
                if binding is fixture["staged_tools"]["trusted_launcher"]
                else 0o700
            )
            self.assertEqual(stat.S_IMODE(tool.stat().st_mode), expected_mode)
            self.assertEqual(sha256(tool.read_bytes()), binding["sha256"])
        base = inputs.operation / fixture["repositories"]["base"]["path"]
        head = inputs.operation / fixture["repositories"]["head"]["path"]
        for label, repository in (("base", base), ("head", head)):
            binding = fixture["repositories"][label]
            self.assertEqual(
                run_git(repository, "rev-parse", "HEAD").stdout.decode().strip(),
                binding["commit"],
            )
            self.assertEqual(
                run_git(repository, "rev-parse", "HEAD^{tree}").stdout.decode().strip(),
                binding["tree"],
            )
            self.assertEqual(run_git(repository, "remote").stdout, b"")
            self.assertEqual(run_git(repository, "status", "--porcelain").stdout, b"")
            recorded_files = {entry["path"]: entry for entry in binding["files"]}
            for source_entry in fixture["source"]["entries"]:
                fixture_entry = recorded_files[source_entry["path"]]
                self.assertEqual(fixture_entry["origin"], "reviewed-source")
                self.assertEqual(fixture_entry["mode"], source_entry["mode"])
                self.assertEqual(fixture_entry["sha256"], source_entry["sha256"])
            tree_records = run_git(
                repository,
                "ls-tree",
                "-r",
                "-z",
                binding["commit"],
            ).stdout
            observed_paths = set()
            for raw_record in filter(None, tree_records.split(b"\0")):
                metadata, raw_path = raw_record.split(b"\t", 1)
                mode, kind, object_id = metadata.split(b" ", 2)
                path = raw_path.decode("ascii")
                observed_paths.add(path)
                self.assertEqual(kind, b"blob")
                self.assertEqual(recorded_files[path]["mode"], mode.decode("ascii"))
                blob = run_git(
                    repository,
                    "cat-file",
                    "blob",
                    object_id.decode("ascii"),
                ).stdout
                self.assertEqual(recorded_files[path]["sha256"], sha256(blob))
            self.assertEqual(observed_paths, set(recorded_files))
            for git_path in (repository / ".git").rglob("*"):
                self.assertEqual(
                    git_path.lstat().st_mode & 0o077,
                    0,
                    os.fspath(git_path),
                )
        source_entries = {
            entry["path"]: entry for entry in fixture["source"]["entries"]
        }
        self.assertEqual(set(source_entries), set(SOURCE_MODES))
        for relative, entry in source_entries.items():
            raw = run_git(
                inputs.source,
                "show",
                f"{inputs.commit}:{relative}",
            ).stdout
            self.assertEqual(entry["mode"], SOURCE_MODES[relative])
            self.assertEqual(entry["sha256"], sha256(raw))

        public_fields = inputs.signer_public_key.read_bytes().split()
        public_blob = base64.b64decode(public_fields[1], validate=True)
        expected_fingerprint = "SHA256:" + base64.b64encode(
            hashlib.sha256(public_blob).digest()
        ).decode("ascii").rstrip("=")
        self.assertEqual(fixture["signer"]["fingerprint"], expected_fingerprint)
        changed = (
            run_git(
                head,
                "diff",
                "--name-only",
                fixture["repositories"]["base"]["commit"],
                fixture["repositories"]["head"]["commit"],
            )
            .stdout.decode("ascii")
            .splitlines()
        )
        self.assertEqual(
            changed,
            [".privacy-age-envelopes.json", "home/private.age"],
        )
        for label, repository in (("base", base), ("head", head)):
            ciphertext = run_git(
                repository,
                "show",
                f"{fixture['repositories'][label]['commit']}:home/private.age",
            ).stdout
            manifest = json.loads(
                run_git(
                    repository,
                    "show",
                    f"{fixture['repositories'][label]['commit']}:.privacy-age-envelopes.json",
                ).stdout
            )
            self.assertEqual(
                manifest,
                {
                    "version": "privacy-age-envelopes/v1",
                    "envelopes": [
                        {
                            "path": "home/private.age",
                            "sha256": "sha256:" + sha256(ciphertext),
                        }
                    ],
                },
            )

    def test_resolves_a_symlinked_temporary_parent_before_building(self) -> None:
        with TemporaryDirectory(prefix="age-admission-fixture-parent.") as directory:
            outer = Path(directory).resolve(strict=True)
            physical_parent = outer / "physical"
            physical_parent.mkdir(mode=0o700)
            lexical_parent = outer / "lexical"
            lexical_parent.symlink_to(physical_parent, target_is_directory=True)
            temporary, inputs = self.make_inputs(temporary_parent=lexical_parent)
            try:
                lexical_root = Path(temporary.name)
                self.assertNotEqual(lexical_root, inputs.root)
                self.assertEqual(lexical_root.resolve(strict=True), inputs.root)

                result = inputs.run_builder()

                self.assertEqual(
                    (result.returncode, result.stdout, result.stderr),
                    (0, b"fixture-ready\n", b""),
                )
                self.assertFalse(inputs.provider_marker.exists())
                self.assertFalse(inputs.network_marker.exists())
            finally:
                temporary.cleanup()

    def test_rejects_real_transition_and_provider_request_members(self) -> None:
        prohibited = {
            "base_commit": "1" * 40,
            "head_commit": "2" * 40,
            "remote": "origin",
            "provider_session": "/tmp/synthetic-provider-session",
            "pass_cli": "/tmp/synthetic-pass-cli",
            "production_repository": "nisavid/dotfiles",
        }
        for name, value in prohibited.items():
            with self.subTest(name=name):
                temporary, inputs = self.make_inputs()
                try:
                    inputs.request_document[name] = value
                    inputs.request.write_bytes(canonical_json(inputs.request_document))
                    inputs.request.chmod(0o600)

                    result = inputs.run_builder()

                    self.assertEqual(
                        (result.returncode, result.stdout, result.stderr),
                        (
                            1,
                            b"",
                            b"age-admission provider fixture failed\n",
                        ),
                    )
                    self.assertFalse(inputs.operation.exists())
                    self.assertFalse(inputs.provider_marker.exists())
                finally:
                    temporary.cleanup()

    def test_requires_isolated_no_bytecode_no_site_python(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "-S", os.fspath(BUILDER)],
            check=False,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (1, b"", b"age-admission provider fixture failed\n"),
        )

    def test_rejects_invalid_missing_or_mismatched_reviewed_source_evidence(
        self,
    ) -> None:
        def missing_entry(inputs: FixtureInputs) -> None:
            inputs.manifest_document["entries"].pop()
            inputs.rewrite_manifest_and_request()

        def declared_mode_mismatch(inputs: FixtureInputs) -> None:
            inputs.manifest_document["entries"][0]["mode"] = "100755"
            inputs.rewrite_manifest_and_request()

        def declared_digest_mismatch(inputs: FixtureInputs) -> None:
            inputs.manifest_document["entries"][0]["sha256"] = "0" * 64
            inputs.rewrite_manifest_and_request()

        def manifest_file_mode(inputs: FixtureInputs) -> None:
            inputs.manifest.chmod(0o644)

        def manifest_file_digest(inputs: FixtureInputs) -> None:
            inputs.request_document["reviewed_source"]["manifest"]["sha256"] = "0" * 64
            inputs.request.write_bytes(canonical_json(inputs.request_document))
            inputs.request.chmod(0o600)

        def raw_source_mode(inputs: FixtureInputs) -> None:
            relative = "scripts/admit-age-envelopes"
            (inputs.source / relative).chmod(0o644)
            run_git(inputs.source, "add", "--all")
            run_git(
                inputs.source,
                "-c",
                "user.name=Synthetic Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--quiet",
                "-m",
                "synthetic source mode mismatch",
            )
            commit = run_git(inputs.source, "rev-parse", "HEAD").stdout.decode().strip()
            inputs.manifest_document["commit"] = commit
            inputs.rewrite_manifest_and_request()

        def raw_source_missing(inputs: FixtureInputs) -> None:
            run_git(inputs.source, "rm", "--quiet", "scripts/privacy-scan")
            run_git(
                inputs.source,
                "-c",
                "user.name=Synthetic Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--quiet",
                "-m",
                "synthetic source missing path",
            )
            commit = run_git(inputs.source, "rev-parse", "HEAD").stdout.decode().strip()
            inputs.manifest_document["commit"] = commit
            inputs.rewrite_manifest_and_request()

        def external_object_alternate(inputs: FixtureInputs) -> None:
            info = inputs.source / ".git/objects/info"
            info.mkdir(mode=0o700, exist_ok=True)
            alternate = info / "alternates"
            alternate.write_text(
                os.fspath(inputs.root / "unreviewed-object-database") + "\n",
                encoding="ascii",
            )
            alternate.chmod(0o600)

        scenarios = {
            "missing manifest entry": missing_entry,
            "declared mode mismatch": declared_mode_mismatch,
            "declared digest mismatch": declared_digest_mismatch,
            "manifest file mode": manifest_file_mode,
            "manifest file digest": manifest_file_digest,
            "raw source mode": raw_source_mode,
            "raw source missing": raw_source_missing,
            "external object alternate": external_object_alternate,
        }
        for name, mutate in scenarios.items():
            with self.subTest(name=name):
                temporary, inputs = self.make_inputs()
                try:
                    mutate(inputs)

                    result = inputs.run_builder()

                    self.assertEqual(
                        (result.returncode, result.stdout, result.stderr),
                        (
                            1,
                            b"",
                            b"age-admission provider fixture failed\n",
                        ),
                    )
                    self.assertFalse(inputs.operation.exists())
                    self.assertFalse(inputs.provider_marker.exists())
                finally:
                    temporary.cleanup()

    def test_rejects_unsafe_input_paths_and_preserves_preexisting_output(
        self,
    ) -> None:
        def request_mode(inputs: FixtureInputs) -> None:
            inputs.request.chmod(0o644)

        def signer_mode(inputs: FixtureInputs) -> None:
            inputs.signer_public_key.chmod(0o644)

        def operation_parent_mode(inputs: FixtureInputs) -> None:
            inputs.operations.chmod(0o755)

        def request_symlink(inputs: FixtureInputs) -> None:
            target = inputs.request.with_name("request-target.json")
            inputs.request.rename(target)
            inputs.request.symlink_to(target.name)

        def manifest_symlink(inputs: FixtureInputs) -> None:
            target = inputs.manifest.with_name("manifest-target.json")
            inputs.manifest.rename(target)
            inputs.manifest.symlink_to(target.name)

        def archive_symlink(inputs: FixtureInputs) -> None:
            target = inputs.archive.with_name("archive-target.tar.gz")
            inputs.archive.rename(target)
            inputs.archive.symlink_to(target.name)

        def source_symlink(inputs: FixtureInputs) -> None:
            target = inputs.source.with_name("source-target")
            inputs.source.rename(target)
            inputs.source.symlink_to(target.name, target_is_directory=True)

        def request_hard_link(inputs: FixtureInputs) -> None:
            os.link(inputs.request, inputs.root / "request-hard-link.json")

        def manifest_hard_link(inputs: FixtureInputs) -> None:
            os.link(inputs.manifest, inputs.root / "manifest-hard-link.json")

        def signer_hard_link(inputs: FixtureInputs) -> None:
            os.link(inputs.signer_public_key, inputs.root / "signer-hard-link.pub")

        scenarios = {
            "request mode": request_mode,
            "signer mode": signer_mode,
            "operation parent mode": operation_parent_mode,
            "request symlink": request_symlink,
            "manifest symlink": manifest_symlink,
            "archive symlink": archive_symlink,
            "source symlink": source_symlink,
            "request hard link": request_hard_link,
            "manifest hard link": manifest_hard_link,
            "signer hard link": signer_hard_link,
        }
        for name, mutate in scenarios.items():
            with self.subTest(name=name):
                temporary, inputs = self.make_inputs()
                try:
                    mutate(inputs)

                    result = inputs.run_builder()

                    self.assertEqual(
                        (result.returncode, result.stdout, result.stderr),
                        (
                            1,
                            b"",
                            b"age-admission provider fixture failed\n",
                        ),
                    )
                    self.assertFalse(inputs.operation.exists())
                    self.assertFalse(inputs.provider_marker.exists())
                finally:
                    temporary.cleanup()

        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.operation.mkdir(mode=0o700)
        witness = inputs.operation / "caller-owned"
        witness.write_text("preserve\n", encoding="ascii")

        result = inputs.run_builder()

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (1, b"", b"age-admission provider fixture failed\n"),
        )
        self.assertEqual(witness.read_text(encoding="ascii"), "preserve\n")

    def test_requires_the_exact_trusted_preflight_result_triple(self) -> None:
        outcomes = (
            (0, b"required\n", b"diagnostic\n"),
            (10, b"not-required\n", b""),
            (11, b"indeterminate\n", b""),
            (0, b"required\n" + b"x" * 33, b""),
        )
        for status, stdout, stderr in outcomes:
            with self.subTest(status=status, stdout=stdout, stderr=stderr):
                temporary, inputs = self.make_inputs()
                try:
                    launcher = (
                        b"#!/usr/bin/python3 -B\n"
                        b"import sys\n"
                        + f"sys.stdout.buffer.write({stdout!r})\n".encode("ascii")
                        + f"sys.stderr.buffer.write({stderr!r})\n".encode("ascii")
                        + f"raise SystemExit({status})\n".encode("ascii")
                    )
                    inputs.replace_reviewed_source(
                        "scripts/run-trusted-age-admission",
                        launcher,
                    )

                    result = inputs.run_builder()

                    self.assertEqual(
                        (result.returncode, result.stdout, result.stderr),
                        (
                            1,
                            b"",
                            b"age-admission provider fixture failed\n",
                        ),
                    )
                    self.assertFalse(inputs.operation.exists())
                    self.assertFalse(inputs.provider_marker.exists())
                finally:
                    temporary.cleanup()

    def test_uses_reviewed_blobs_instead_of_source_worktree_bytes(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        source_launcher = inputs.source / "scripts/run-trusted-age-admission"
        source_launcher.write_text(
            "#!/bin/sh\npass-cli item list\n",
            encoding="ascii",
        )
        source_launcher.chmod(0o755)
        candidate_module = inputs.source / "scripts/privacy_age_admission.py"
        candidate_module.write_text(
            "from pathlib import Path\n"
            f"Path({os.fspath(inputs.provider_marker)!r}).write_text('imported')\n",
            encoding="ascii",
        )

        result = inputs.run_builder()

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, b"fixture-ready\n", b""),
        )
        self.assertFalse(inputs.provider_marker.exists())
        fixture = json.loads((inputs.operation / "fixture.json").read_bytes())
        staged_launcher = (
            inputs.operation / fixture["staged_tools"]["trusted_launcher"]["path"]
        )
        self.assertEqual(
            staged_launcher.read_bytes(), FixtureInputs.trusted_launcher_stub()
        )

    def test_rejects_a_running_builder_that_differs_from_its_reviewed_blob(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        changed_builder = inputs.root / "changed-builder"
        changed_builder.write_bytes(
            BUILDER.read_bytes() + b"\n# changed candidate byte\n"
        )
        changed_builder.chmod(0o700)

        result = inputs.run_builder(changed_builder)

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (1, b"", b"age-admission provider fixture failed\n"),
        )
        self.assertFalse(inputs.operation.exists())

    def test_caught_signal_reaps_child_and_removes_unbound_operation(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        child_marker = inputs.root / "age-child-pid"
        self.configure_slow_age_child(inputs, child_marker)
        process = subprocess.Popen(
            inputs.builder_command(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=inputs.builder_environment(),
            start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while not child_marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(child_marker.exists(), "slow age child did not start")
        child_pid = int(child_marker.read_text(encoding="ascii"))

        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (143, b"", b"age-admission provider fixture interrupted\n"),
        )
        self.assertFalse(inputs.operation.exists())
        self.assertFalse(inputs.provider_marker.exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_transient_group_probe_uncertainty_is_retried(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)

        outcome, process_group = self._run_with_group_probe_fault(
            inputs, persistent=False
        )

        self.assertEqual(
            outcome,
            (143, b"", b"age-admission provider fixture interrupted\n"),
        )
        with self.assertRaises(ProcessLookupError):
            os.killpg(process_group, 0)
        self.assertFalse(inputs.operation.exists())
        self.assertFalse(inputs.provider_marker.exists())
        self.assertFalse(inputs.network_marker.exists())

    def test_persistent_group_probe_uncertainty_fails_closed(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)

        outcome, process_group = self._run_with_group_probe_fault(
            inputs, persistent=True
        )

        self.assertEqual(
            outcome,
            (1, b"", b"age-admission provider fixture failed\n"),
        )
        with self.assertRaises(ProcessLookupError):
            os.killpg(process_group, 0)
        self.assertFalse(inputs.operation.exists())
        self.assertFalse(inputs.provider_marker.exists())
        self.assertFalse(inputs.network_marker.exists())

    def test_zombie_only_probe_uncertainty_clears_after_leader_reap(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)

        outcome, process_group = self._run_with_group_probe_fault(
            inputs, persistent=False, until_reaped=True
        )

        self.assertEqual(
            outcome,
            (143, b"", b"age-admission provider fixture interrupted\n"),
        )
        with self.assertRaises(ProcessLookupError):
            os.killpg(process_group, 0)
        self.assertFalse(inputs.operation.exists())
        self.assertFalse(inputs.provider_marker.exists())
        self.assertFalse(inputs.network_marker.exists())

    def test_repeated_signals_during_operation_cleanup_keep_the_first_status(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        child_marker = inputs.root / "age-child-pid"
        cleanup_started = inputs.root / "cleanup-started"
        cleanup_release = inputs.root / "cleanup-release"
        cleanup_count = inputs.root / "cleanup-count"
        self.configure_slow_age_child(inputs, child_marker)
        harness = textwrap.dedent(
            f"""\
            import os
            import pathlib
            import runpy
            import shutil
            import sys
            import time

            operation = pathlib.Path({os.fspath(inputs.operation)!r})
            real_rmtree = shutil.rmtree
            calls = 0

            def paused_rmtree(path, *arguments, **keywords):
                global calls
                if pathlib.Path(path) == operation:
                    calls += 1
                    pathlib.Path({os.fspath(cleanup_started)!r}).write_text(
                        "started", encoding="ascii"
                    )
                    deadline = time.monotonic() + 5
                    release = pathlib.Path({os.fspath(cleanup_release)!r})
                    while not release.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                return real_rmtree(path, *arguments, **keywords)

            shutil.rmtree = paused_rmtree
            source = sys.argv[1]
            sys.argv = [source, *sys.argv[2:]]
            try:
                runpy.run_path(source, run_name="__main__")
            finally:
                pathlib.Path({os.fspath(cleanup_count)!r}).write_text(
                    str(calls), encoding="ascii"
                )
            """
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                "-c",
                harness,
                os.fspath(BUILDER),
                *inputs.builder_command()[5:],
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=inputs.builder_environment(),
            start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while not child_marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(child_marker.exists(), "slow age child did not start")
        child_pid = int(child_marker.read_text(encoding="ascii"))

        process.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 5
        while not cleanup_started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(cleanup_started.exists(), "operation cleanup did not start")
        process.send_signal(signal.SIGINT)
        process.send_signal(signal.SIGHUP)
        cleanup_release.write_text("release", encoding="ascii")
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(
            (process.returncode, stdout, stderr),
            (143, b"", b"age-admission provider fixture interrupted\n"),
        )
        self.assertEqual(cleanup_count.read_text(encoding="ascii"), "1")
        self.assertFalse(inputs.operation.exists())
        self.assertFalse(inputs.provider_marker.exists())
        self.assertFalse(inputs.network_marker.exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_signal_with_unverified_operation_cleanup_reports_failure(self) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        child_marker = inputs.root / "age-child-pid"
        retained_operation_path = inputs.root / "retained-operation.path"
        self.configure_slow_age_child(inputs, child_marker)
        harness = textwrap.dedent(
            f"""\
            import os
            import pathlib
            import runpy
            import shutil
            import sys

            operation = pathlib.Path({os.fspath(inputs.operation)!r})
            real_rmtree = shutil.rmtree

            def failing_rmtree(path, *arguments, **keywords):
                if pathlib.Path(path) == operation:
                    pathlib.Path({os.fspath(retained_operation_path)!r}).write_text(
                        os.fspath(path), encoding="utf-8"
                    )
                    raise OSError("synthetic cleanup uncertainty")
                return real_rmtree(path, *arguments, **keywords)

            shutil.rmtree = failing_rmtree
            source = sys.argv[1]
            sys.argv = [source, *sys.argv[2:]]
            runpy.run_path(source, run_name="__main__")
            """
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                "-c",
                harness,
                os.fspath(BUILDER),
                *inputs.builder_command()[5:],
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=inputs.builder_environment(),
            start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while not child_marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(child_marker.exists(), "slow age child did not start")

        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)

        retained_operation = Path(retained_operation_path.read_text(encoding="utf-8"))
        retained = retained_operation.exists()
        if retained:
            shutil.rmtree(retained_operation)
        self.assertEqual(
            (process.returncode, stdout, stderr),
            (1, b"", b"age-admission provider fixture failed\n"),
        )
        self.assertTrue(retained)
        self.assertFalse(inputs.provider_marker.exists())
        self.assertFalse(inputs.network_marker.exists())

    def test_signal_during_popen_acquisition_retires_the_real_child_group(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        boundary_child_path = inputs.root / "boundary-child.pid"
        harness = textwrap.dedent(
            f"""\
            import os
            import pathlib
            import runpy
            import signal
            import subprocess
            import sys

            real_popen = subprocess.Popen
            triggered = False

            def signal_before_return(_command, *arguments, **keywords):
                global triggered
                if triggered:
                    return real_popen(_command, *arguments, **keywords)
                triggered = True
                process = real_popen(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    *arguments,
                    **keywords,
                )
                pathlib.Path({os.fspath(boundary_child_path)!r}).write_text(
                    str(process.pid), encoding="ascii"
                )
                os.kill(os.getpid(), signal.SIGTERM)
                return process

            subprocess.Popen = signal_before_return
            source = sys.argv[1]
            sys.argv = [source, *sys.argv[2:]]
            runpy.run_path(source, run_name="__main__")
            """
        )

        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                "-c",
                harness,
                os.fspath(BUILDER),
                *inputs.builder_command()[5:],
            ],
            check=False,
            capture_output=True,
            env=inputs.builder_environment(),
            start_new_session=True,
            timeout=10,
        )

        child_pid = int(boundary_child_path.read_text(encoding="ascii"))
        child_survived = True
        try:
            os.killpg(child_pid, 0)
        except ProcessLookupError:
            child_survived = False
        if child_survived:
            os.killpg(child_pid, signal.SIGKILL)
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (143, b"", b"age-admission provider fixture interrupted\n"),
        )
        self.assertFalse(child_survived)
        self.assertFalse(inputs.operation.exists())
        self.assertFalse(inputs.provider_marker.exists())
        self.assertFalse(inputs.network_marker.exists())

    def test_signal_during_operation_acquisition_stops_before_another_effect(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        later_effect_path = inputs.root / "later-mkdir.path"
        harness = textwrap.dedent(
            f"""\
            import os
            import pathlib
            import runpy
            import signal
            import sys

            operation = pathlib.Path({os.fspath(inputs.operation)!r})
            real_mkdir = pathlib.Path.mkdir
            triggered = False

            def signal_after_create(path, *arguments, **keywords):
                global triggered
                if triggered and path != operation:
                    pathlib.Path({os.fspath(later_effect_path)!r}).write_text(
                        os.fspath(path), encoding="utf-8"
                    )
                result = real_mkdir(path, *arguments, **keywords)
                if path == operation and not triggered:
                    triggered = True
                    os.kill(os.getpid(), signal.SIGTERM)
                return result

            pathlib.Path.mkdir = signal_after_create
            source = sys.argv[1]
            sys.argv = [source, *sys.argv[2:]]
            runpy.run_path(source, run_name="__main__")
            """
        )

        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                "-c",
                harness,
                os.fspath(BUILDER),
                *inputs.builder_command()[5:],
            ],
            check=False,
            capture_output=True,
            env=inputs.builder_environment(),
            start_new_session=True,
            timeout=10,
        )

        operation_survived = inputs.operation.exists()
        if operation_survived:
            shutil.rmtree(inputs.operation)
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (143, b"", b"age-admission provider fixture interrupted\n"),
        )
        self.assertFalse(operation_survived)
        self.assertFalse(later_effect_path.exists())
        self.assertFalse(inputs.provider_marker.exists())
        self.assertFalse(inputs.network_marker.exists())

    def test_inherited_termination_mask_cannot_delay_first_signal_cleanup(
        self,
    ) -> None:
        termination_signals = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
        termination_numbers = {int(signum) for signum in termination_signals}

        def process_exists(pid: int) -> bool:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            return True

        def group_exists(process_group: int) -> bool:
            try:
                os.killpg(process_group, 0)
            except ProcessLookupError:
                return False
            return True

        for signum in termination_signals:
            with self.subTest(signum=signum.name):
                temporary, inputs = self.make_inputs()
                process: subprocess.Popen[bytes] | None = None
                child_started = False
                state: dict[str, object] = {}
                completion: tuple[int, bytes, bytes] | None = None
                builder_group_survived = False
                child_pid_survived = False
                child_group_survived = False
                operation_survived = False
                fixture_published = False
                provider_accessed = False
                network_accessed = False
                try:
                    child_state = inputs.root / "masked-child.json"
                    launcher = f"#!{sys.executable} -B\n".encode() + textwrap.dedent(
                        f"""\
                        import json
                        import os
                        import pathlib
                        import signal
                        import time

                        termination_signals = (
                            signal.SIGHUP,
                            signal.SIGINT,
                            signal.SIGTERM,
                        )
                        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set())
                        ignored = {{
                            str(int(item)): signal.getsignal(item) == signal.SIG_IGN
                            for item in termination_signals
                        }}
                        state_path = pathlib.Path({os.fspath(child_state)!r})
                        pending_state = state_path.with_name(state_path.name + ".pending")
                        pending_state.write_text(
                            json.dumps(
                                {{
                                    "blocked": sorted(int(item) for item in blocked),
                                    "ignored": ignored,
                                    "pgid": os.getpgrp(),
                                    "pid": os.getpid(),
                                }},
                                sort_keys=True,
                            ),
                            encoding="ascii",
                        )
                        os.replace(pending_state, state_path)
                        time.sleep(30)
                        print("required")
                        """
                    ).encode("ascii")
                    inputs.replace_reviewed_source(
                        "scripts/run-trusted-age-admission",
                        launcher,
                    )
                    blocked_parent = textwrap.dedent(
                        """\
                        import os
                        import signal
                        import sys

                        termination_signals = (
                            signal.SIGHUP,
                            signal.SIGINT,
                            signal.SIGTERM,
                        )
                        for item in termination_signals:
                            signal.signal(item, signal.SIG_IGN)
                        signal.pthread_sigmask(signal.SIG_BLOCK, termination_signals)
                        os.execve(
                            sys.executable,
                            [
                                sys.executable,
                                "-I",
                                "-B",
                                "-S",
                                *sys.argv[1:],
                            ],
                            os.environ,
                        )
                        """
                    )
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-I",
                            "-B",
                            "-S",
                            "-c",
                            blocked_parent,
                            *inputs.builder_command()[4:],
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=inputs.builder_environment(),
                        start_new_session=True,
                    )
                    deadline = time.monotonic() + 5
                    while not child_state.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    child_started = child_state.exists()
                    if child_started:
                        state = json.loads(child_state.read_bytes())
                        process.send_signal(signum)
                        try:
                            stdout, stderr = process.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            pass
                        else:
                            if process.returncode is not None:
                                completion = (process.returncode, stdout, stderr)

                    builder_group_survived = group_exists(process.pid)
                    child_pid = state.get("pid")
                    child_group = state.get("pgid")
                    if isinstance(child_pid, int):
                        child_pid_survived = process_exists(child_pid)
                    if isinstance(child_group, int):
                        child_group_survived = group_exists(child_group)
                    operation_survived = inputs.operation.exists()
                    fixture_published = (inputs.operation / "fixture.json").exists()
                    provider_accessed = inputs.provider_marker.exists()
                    network_accessed = inputs.network_marker.exists()
                finally:
                    child_group = state.get("pgid")
                    if isinstance(child_group, int) and group_exists(child_group):
                        try:
                            os.killpg(child_group, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    if process is not None:
                        if group_exists(process.pid):
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        if process.poll() is None:
                            process.kill()
                        try:
                            process.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.communicate(timeout=5)
                    if inputs.operation.exists():
                        shutil.rmtree(inputs.operation)
                    temporary.cleanup()

                self.assertTrue(child_started, "task-owned child did not start")
                self.assertEqual(
                    set(state["blocked"]).intersection(termination_numbers),
                    set(),
                )
                self.assertFalse(any(state["ignored"].values()))
                self.assertEqual(
                    completion,
                    (
                        128 + signum,
                        b"",
                        b"age-admission provider fixture interrupted\n",
                    ),
                )
                self.assertFalse(builder_group_survived)
                self.assertFalse(child_pid_survived)
                self.assertFalse(child_group_survived)
                self.assertFalse(operation_survived)
                self.assertFalse(fixture_published)
                self.assertFalse(provider_accessed)
                self.assertFalse(network_accessed)

    def test_normal_child_with_resistant_descendant_is_retired_and_fails(
        self,
    ) -> None:
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        descendant_state = inputs.root / "resistant-descendant.json"
        descendant_source = textwrap.dedent(
            f"""\
            import json
            import os
            import pathlib
            import signal
            import time

            termination_signals = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
            blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set())
            inherited_ignored = {{
                str(int(signum)): signal.getsignal(signum) == signal.SIG_IGN
                for signum in termination_signals
            }}
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            pathlib.Path({os.fspath(descendant_state)!r}).write_text(
                json.dumps(
                    {{
                        "blocked": sorted(int(signum) for signum in blocked),
                        "inherited_ignored": inherited_ignored,
                        "pgid": os.getpgrp(),
                        "pid": os.getpid(),
                    }},
                    sort_keys=True,
                ),
                encoding="ascii",
            )
            time.sleep(30)
            """
        )
        launcher = f"#!{sys.executable} -B\n".encode() + textwrap.dedent(
            f"""\
                import pathlib
                import subprocess
                import sys
                import time

                state = pathlib.Path({os.fspath(descendant_state)!r})
                subprocess.Popen(
                    [sys.executable, "-c", {descendant_source!r}],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                deadline = time.monotonic() + 5
                while not state.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if not state.exists():
                    raise SystemExit(95)
                print("required")
                """
        ).encode("ascii")
        inputs.replace_reviewed_source("scripts/run-trusted-age-admission", launcher)

        result = inputs.run_builder()

        state = json.loads(descendant_state.read_bytes())
        descendant_pid = state["pid"]
        process_group = state["pgid"]
        pid_survived = True
        group_survived = True
        try:
            os.kill(descendant_pid, 0)
        except ProcessLookupError:
            pid_survived = False
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            group_survived = False
        if group_survived:
            os.killpg(process_group, signal.SIGKILL)
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (1, b"", b"age-admission provider fixture failed\n"),
        )
        self.assertEqual(
            set(state["blocked"]).intersection(
                {int(signal.SIGHUP), int(signal.SIGINT), int(signal.SIGTERM)}
            ),
            set(),
        )
        self.assertFalse(any(state["inherited_ignored"].values()))
        self.assertFalse(pid_survived)
        self.assertFalse(group_survived)
        self.assertFalse(inputs.operation.exists())
        self.assertFalse(inputs.provider_marker.exists())
        self.assertFalse(inputs.network_marker.exists())

    def test_real_receipt_is_bound_away_from_other_transition_and_repository(
        self,
    ) -> None:
        age_archive, age_archive_sha256 = selected_age_tooling_archive_or_skip()
        ssh_keygen = resolved_non_provider_support("ssh-keygen")
        temporary, inputs = self.make_inputs(
            real_launcher=True,
            temporary_parent=ROOT.parent,
        )
        self.addCleanup(temporary.cleanup)
        if not self.trusted_path_ancestors_supported(inputs.root):
            self.skipTest("trusted-wrapper ancestors are UID-mapped in this sandbox")

        signing_key = inputs.root / "admission-signer"
        generated = subprocess.run(
            [ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-f", os.fspath(signing_key)],
            check=False,
            capture_output=True,
            timeout=15,
        )
        if generated.returncode != 0:
            self.skipTest("disposable SSH Ed25519 key generation is unavailable")
        signer_public_key = Path(f"{signing_key}.pub")
        signer_public_key.chmod(0o600)
        inputs.signer_public_key = signer_public_key
        inputs.request_document["signer_public_key"] = os.fspath(signer_public_key)
        inputs.request_document["age_tooling"] = {
            "archive": os.fspath(age_archive),
            "sha256": age_archive_sha256,
        }
        inputs.request.write_bytes(canonical_json(inputs.request_document))
        inputs.request.chmod(0o600)

        built = inputs.run_builder()
        self.assertEqual(
            (built.returncode, built.stdout, built.stderr),
            (0, b"fixture-ready\n", b""),
        )
        fixture = json.loads((inputs.operation / "fixture.json").read_bytes())
        base_binding = fixture["repositories"]["base"]
        head_binding = fixture["repositories"]["head"]
        base = inputs.operation / base_binding["path"]
        head = inputs.operation / head_binding["path"]
        launcher = (
            inputs.operation / fixture["staged_tools"]["trusted_launcher"]["path"]
        )
        identity = inputs.operation / fixture["age_identity"]["path"]
        receipt = inputs.root / "fixture-receipt"
        receipt_support = inputs.root / "receipt-support-tools"
        receipt_support.mkdir(mode=0o700)
        for name in sorted(NON_PROVIDER_SUPPORT):
            (receipt_support / name).symlink_to(resolved_non_provider_support(name))
        environment = {
            "AGE_TOOLING_DIRECTORY": os.fspath(inputs.operation / "tools"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": os.fspath(inputs.root / "home"),
            "LC_ALL": "C",
            "PATH": os.pathsep.join(
                (os.fspath(inputs.operation / "tools"), os.fspath(receipt_support))
            ),
            "PYTHONPYCACHEPREFIX": os.fspath(inputs.root / "pycache"),
            "TEMP": os.fspath(inputs.root),
            "TMP": os.fspath(inputs.root),
            "TMPDIR": os.fspath(inputs.root),
        }
        created = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-S",
                os.fspath(launcher),
                "--base-repository",
                os.fspath(base),
                "--base-commit",
                base_binding["commit"],
                "--",
                "--operation",
                "create-receipt",
                "--base-repository",
                os.fspath(base),
                "--base-commit",
                base_binding["commit"],
                "--head-repository",
                os.fspath(head),
                "--head-commit",
                head_binding["commit"],
                "--repository",
                fixture["authority"]["repository"],
                "--identity",
                os.fspath(identity),
                "--signing-key",
                os.fspath(signing_key),
                "--trusted-admitter",
                os.fspath(base / "scripts/admit-age-envelopes"),
                "--output",
                os.fspath(receipt),
                "--lifetime-seconds",
                "600",
            ],
            check=False,
            capture_output=True,
            env=environment,
            timeout=90,
        )
        self.assertEqual(
            (created.returncode, created.stdout, created.stderr),
            (0, b"", b""),
        )
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)

        def verify(
            repository: str, head_commit: str
        ) -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-S",
                    os.fspath(base / "scripts/privacy_age_integrity_gate.py"),
                    "--base-repository",
                    os.fspath(base),
                    "--base-commit",
                    base_binding["commit"],
                    "--head-repository",
                    os.fspath(head),
                    "--head-commit",
                    head_commit,
                    "--admission-body",
                    os.fspath(receipt),
                    "--allowed-signers",
                    os.fspath(base / ".github/age-admission/allowed_signers"),
                    "--repository",
                    repository,
                ],
                check=False,
                capture_output=True,
                env=environment,
                timeout=30,
            )

        accepted = verify(fixture["authority"]["repository"], head_binding["commit"])
        self.assertEqual(
            (accepted.returncode, accepted.stdout, accepted.stderr),
            (0, b"privacy age integrity boundary verified\n", b""),
        )
        wrong_repository = verify("nisavid/dotfiles", head_binding["commit"])
        self.assertEqual(wrong_repository.returncode, 1)
        self.assertEqual(wrong_repository.stdout, b"")
        self.assertEqual(
            wrong_repository.stderr,
            b"privacy age integrity gate failed: admission receipt is not authorized\n",
        )

        (head / "home/private.age").write_bytes(b"different synthetic transition\n")
        run_git(head, "add", "--", "home/private.age")
        run_git(
            head,
            "-c",
            "user.name=Synthetic Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "different synthetic transition",
        )
        different_head = run_git(head, "rev-parse", "HEAD").stdout.decode().strip()
        wrong_transition = verify(fixture["authority"]["repository"], different_head)
        self.assertEqual(wrong_transition.returncode, 1)
        self.assertEqual(wrong_transition.stdout, b"")
        self.assertEqual(
            wrong_transition.stderr,
            b"privacy age integrity gate failed: admission receipt is not authorized\n",
        )
        self.assertFalse(inputs.provider_marker.exists())
        receipt.unlink()
        self.assertFalse(receipt.exists())

    def test_builds_genuine_pq_ciphertexts_with_checksum_bound_public_age_tooling(
        self,
    ) -> None:
        age_archive, age_archive_sha256 = selected_age_tooling_archive_or_skip()
        temporary, inputs = self.make_inputs()
        self.addCleanup(temporary.cleanup)
        inputs.request_document["age_tooling"] = {
            "archive": os.fspath(age_archive),
            "sha256": age_archive_sha256,
        }
        inputs.request.write_bytes(canonical_json(inputs.request_document))
        inputs.request.chmod(0o600)

        result = inputs.run_builder()

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, b"fixture-ready\n", b""),
        )
        fixture = json.loads((inputs.operation / "fixture.json").read_bytes())
        identity = inputs.operation / fixture["age_identity"]["path"]
        tools = inputs.operation / "tools"
        derived = subprocess.run(
            [os.fspath(tools / "age-keygen"), "-y", os.fspath(identity)],
            check=False,
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(
            (derived.returncode, derived.stdout, derived.stderr),
            (0, (fixture["age_identity"]["recipient"] + "\n").encode("ascii"), b""),
        )
        for label, plaintext in (
            ("base", b"issue286 synthetic provider fixture base\n"),
            ("head", b"issue286 synthetic provider fixture head\n"),
        ):
            binding = fixture["repositories"][label]
            repository = inputs.operation / binding["path"]
            ciphertext = run_git(
                repository,
                "show",
                f"{binding['commit']}:home/private.age",
            ).stdout
            decrypted = subprocess.run(
                [
                    os.fspath(tools / "age"),
                    "--decrypt",
                    "--identity",
                    os.fspath(identity),
                    "-",
                ],
                input=ciphertext,
                check=False,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(
                (decrypted.returncode, decrypted.stdout, decrypted.stderr),
                (0, plaintext, b""),
            )
        self.assertFalse(inputs.provider_marker.exists())


if __name__ == "__main__":
    unittest.main()
