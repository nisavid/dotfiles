from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from scripts.privacy_age_envelopes import (
    MAX_AGE_ENVELOPE_BYTES,
    MAX_AGE_MANIFEST_BYTES,
    AgeEnvelopeError,
    age_inspection_has_exact_postquantum_stanzas,
    canonical_manifest_bytes,
    discover_age_files,
)
from tests.age_tooling_test_support import (
    require_age_tooling_or_skip,
    shared_age_tooling_directory_or_skip,
)

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts/privacy-scan"
ADMITTER = ROOT / "scripts/admit-age-envelopes"
AGE_VERSION = "v1.3.1"
MANIFEST = ".privacy-age-envelopes.json"
MANIFEST_VERSION = "privacy-age-envelopes/v1"
TOOL_TIMEOUT_SECONDS = 10


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def manifest_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    document = {
        "version": MANIFEST_VERSION,
        "envelopes": [
            {"path": path, "sha256": sha256(data)} for path, data in sorted(entries)
        ],
    }
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def verify_age_tooling() -> Path:
    binaries = {
        name: shutil.which(name) for name in ("age", "age-keygen", "age-inspect")
    }
    if any(binary is None for binary in binaries.values()):
        require_age_tooling_or_skip("age v1.3.1 tooling is unavailable")
    try:
        versions = {
            name: subprocess.run(
                [binary, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=TOOL_TIMEOUT_SECONDS,
            )
            for name, binary in binaries.items()
            if binary is not None
        }
    except (OSError, subprocess.TimeoutExpired) as error:
        require_age_tooling_or_skip(
            "age v1.3.1 tooling is unavailable",
            cause=error,
        )
    if any(
        result.returncode != 0 or result.stdout.strip() != AGE_VERSION
        for result in versions.values()
    ):
        require_age_tooling_or_skip("age v1.3.1 tooling is unavailable")
    return shared_age_tooling_directory_or_skip(
        (binary for binary in binaries.values() if binary is not None),
        "age v1.3.1 tooling does not share one trusted install directory",
    )


class PrivacyAgeToolingPolicyTests(TestCase):
    def test_optional_and_required_tooling_policy(self) -> None:
        scenarios = {
            "missing": {
                "which": None,
                "run": None,
            },
            "version-mismatch": {
                "which": "/tools/age",
                "run": subprocess.CompletedProcess(
                    ["age", "--version"],
                    0,
                    stdout="v9.9.9\n",
                    stderr="",
                ),
            },
            "os-error": {
                "which": "/tools/age",
                "run": OSError("unavailable"),
            },
            "timeout": {
                "which": "/tools/age",
                "run": subprocess.TimeoutExpired(["age", "--version"], 1),
            },
        }
        for required, expected in (
            (False, unittest.SkipTest),
            (True, AssertionError),
        ):
            for name, scenario in scenarios.items():
                with (
                    self.subTest(required=required, scenario=name),
                    mock.patch.dict(
                        os.environ,
                        {"REQUIRE_AGE_TOOLING": "1" if required else "0"},
                    ),
                    mock.patch(
                        "shutil.which",
                        return_value=scenario["which"],
                    ),
                    mock.patch(
                        "subprocess.run",
                        side_effect=(
                            scenario["run"]
                            if isinstance(scenario["run"], BaseException)
                            else None
                        ),
                        return_value=(
                            scenario["run"]
                            if isinstance(scenario["run"], subprocess.CompletedProcess)
                            else None
                        ),
                    ),
                    self.assertRaises(
                        expected,
                    ),
                ):
                    verify_age_tooling()


class PrivacyAgeEnvelopeTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.age_tooling_directory = verify_age_tooling()

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.base = Path(self.temporary_directory.name)
        self.root = self.base / "repository"
        self.root.mkdir()
        self.identity = self.base / "identity.txt"
        subprocess.run(
            ["age-keygen", "-pq", "-o", str(self.identity)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=TOOL_TIMEOUT_SECONDS,
        )
        self.recipient = subprocess.run(
            ["age-keygen", "-y", str(self.identity)],
            check=True,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SECONDS,
        ).stdout.strip()

    def run_scanner(self) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["AGE_TOOLING_DIRECTORY"] = os.fspath(
            self.age_tooling_directory
        )
        return subprocess.run(
            [sys.executable, str(SCANNER), "--root", str(self.root)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=TOOL_TIMEOUT_SECONDS,
        )

    def run_admitter(self) -> subprocess.CompletedProcess[str]:
        return self.run_admitter_with(identity=self.identity)

    def run_admitter_with(
        self,
        *,
        identity: Path,
        additional_identities: list[Path] | None = None,
        check_only: bool = False,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(ADMITTER),
            "--root",
            str(self.root),
            "--identity",
            str(identity),
        ]
        for additional_identity in additional_identities or []:
            command.extend(("--identity", str(additional_identity)))
        if check_only:
            command.append("--check-only")
        effective_environment = (
            os.environ.copy() if environment is None else environment.copy()
        )
        effective_environment.setdefault(
            "AGE_TOOLING_DIRECTORY",
            os.fspath(self.age_tooling_directory),
        )
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=effective_environment,
            timeout=TOOL_TIMEOUT_SECONDS,
        )

    def encrypt(
        self,
        plaintext: bytes,
        *,
        armor: bool = False,
        recipients: list[str] | None = None,
    ) -> bytes:
        command = ["age", "--encrypt"]
        for recipient in recipients or [self.recipient]:
            command.extend(("--recipient", recipient))
        if armor:
            command.append("--armor")
        return subprocess.run(
            command,
            input=plaintext,
            check=True,
            capture_output=True,
            timeout=TOOL_TIMEOUT_SECONDS,
        ).stdout

    def armor(self, native: bytes) -> bytes:
        encoded = base64.b64encode(native).decode("ascii")
        body = "\n".join(textwrap.wrap(encoded, width=64))
        return (
            "-----BEGIN AGE ENCRYPTED FILE-----\n"
            + body
            + "\n-----END AGE ENCRYPTED FILE-----\n"
        ).encode("ascii")

    def write_manifest(self, entries: list[tuple[str, bytes]]) -> None:
        (self.root / MANIFEST).write_bytes(manifest_bytes(entries))

    def inspect(self, data: bytes) -> dict[str, object]:
        result = subprocess.run(
            ["age-inspect", "--json", "-"],
            input=data,
            check=True,
            capture_output=True,
            timeout=TOOL_TIMEOUT_SECONDS,
        )
        document = json.loads(result.stdout)
        self.assertIsInstance(document, dict)
        return document

    def make_identity(self, name: str, *, postquantum: bool = True) -> tuple[Path, str]:
        identity = self.base / name
        command = ["age-keygen"]
        if postquantum:
            command.append("-pq")
        command.extend(("-o", str(identity)))
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=TOOL_TIMEOUT_SECONDS,
        )
        recipient = subprocess.run(
            ["age-keygen", "-y", str(identity)],
            check=True,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SECONDS,
        ).stdout.strip()
        return identity, recipient

    def test_scanner_rejects_plaintext_appended_to_a_manifested_native_envelope(
        self,
    ) -> None:
        relative = "ciphertext.age"
        valid = (ROOT / "home/.private-prd-01.toml.age").read_bytes()
        path = self.root / relative
        path.write_bytes(valid)
        self.write_manifest([(relative, valid)])

        clean = self.run_scanner()
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)

        credential = "ghp_" + "A" * 36
        path.write_bytes(valid + b"\n" + credential.encode("ascii") + b"\n")
        result = self.run_scanner()

        self.assertEqual(result.returncode, 1)
        self.assertIn("ciphertext.age:0: [invalid-age-envelope]", result.stdout)
        self.assertIn("ciphertext.age:", result.stdout)
        self.assertIn("[provider-token]", result.stdout)
        self.assertNotIn(credential, result.stdout + result.stderr)

    def test_admission_decrypts_native_and_armored_binary_envelopes_to_eof(
        self,
    ) -> None:
        native = self.encrypt(b"\x00binary\xffpayload")
        armored = self.encrypt(b"armored payload", armor=True)
        (self.root / "native.age").write_bytes(native)
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "armored.age").write_bytes(armored)

        result = self.run_admitter()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            (self.root / MANIFEST).read_bytes(),
            manifest_bytes([("native.age", native), ("nested/armored.age", armored)]),
        )
        scan = self.run_scanner()
        self.assertEqual(scan.returncode, 0, scan.stdout + scan.stderr)

    def test_check_only_admission_validates_without_replacing_the_manifest(self) -> None:
        candidate = self.encrypt(b"check-only fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        expected = manifest_bytes([("candidate.age", candidate)])
        (self.root / MANIFEST).write_bytes(expected)
        original_inode = (self.root / MANIFEST).stat().st_ino

        result = self.run_admitter_with(identity=self.identity, check_only=True)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertEqual((self.root / MANIFEST).read_bytes(), expected)
        self.assertEqual((self.root / MANIFEST).stat().st_ino, original_inode)
        self.assertEqual(list(self.root.glob(f"{MANIFEST}.*")), [])

        (self.root / MANIFEST).write_bytes(manifest_bytes([]))
        result = self.run_admitter_with(identity=self.identity, check_only=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), manifest_bytes([]))
        self.assertEqual(list(self.root.glob(f"{MANIFEST}.*")), [])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "descriptor passing requires POSIX")
    def test_admission_uses_a_held_identity_descriptor_after_path_replacement(self) -> None:
        candidate = self.encrypt(b"descriptor-bound fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        expected = manifest_bytes([("candidate.age", candidate)])
        (self.root / MANIFEST).write_bytes(expected)

        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(self.identity, flags)
        moved = self.identity.with_name("identity-moved.txt")
        try:
            os.replace(self.identity, moved)
            self.identity.write_text("not an age identity\n", encoding="ascii")
            self.identity.chmod(0o000)
            environment = os.environ.copy()
            environment["AGE_TOOLING_DIRECTORY"] = os.fspath(self.age_tooling_directory)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ADMITTER),
                    "--root",
                    str(self.root),
                    "--identity-fd",
                    str(descriptor),
                    "--check-only",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                pass_fds=(descriptor,),
                timeout=TOOL_TIMEOUT_SECONDS,
            )
        finally:
            os.close(descriptor)
            if self.identity.exists():
                self.identity.chmod(0o600)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / MANIFEST).read_bytes(), expected)

        wrong_identity, _ = self.make_identity("wrong-identity.txt")
        wrong_descriptor = os.open(wrong_identity, flags)
        try:
            wrong_result = subprocess.run(
                [
                    sys.executable,
                    str(ADMITTER),
                    "--root",
                    str(self.root),
                    "--identity-fd",
                    str(wrong_descriptor),
                    "--check-only",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                pass_fds=(wrong_descriptor,),
                timeout=TOOL_TIMEOUT_SECONDS,
            )
        finally:
            os.close(wrong_descriptor)
        self.assertEqual(wrong_result.returncode, 1)
        self.assertEqual((self.root / MANIFEST).read_bytes(), expected)

    def test_admission_rejects_an_additional_postquantum_recipient(self) -> None:
        _, additional_recipient = self.make_identity("additional-identity.txt")
        candidate = self.encrypt(
            b"unauthorized recipient fixture",
            recipients=[self.recipient, additional_recipient],
        )
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)

        result = self.run_admitter()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_hosted_policy_accepts_exactly_one_postquantum_stanza(self) -> None:
        _, additional_recipient = self.make_identity("additional-identity.txt")
        one_recipient = self.encrypt(b"one recipient")
        two_recipients = self.encrypt(
            b"two recipients",
            recipients=[self.recipient, additional_recipient],
        )

        self.assertTrue(
            age_inspection_has_exact_postquantum_stanzas(
                self.inspect(one_recipient),
                stanza_count=1,
            )
        )
        self.assertFalse(
            age_inspection_has_exact_postquantum_stanzas(
                self.inspect(two_recipients),
                stanza_count=1,
            )
        )

    def test_hosted_policy_rejects_malformed_age_inspection_metadata(self) -> None:
        valid = self.inspect(self.encrypt(b"inspection metadata fixture"))
        valid_sizes = valid["sizes"]
        self.assertIsInstance(valid_sizes, dict)
        cases = {
            "non-PQ marker": {**valid, "postquantum": "no"},
            "non-boolean armor": {**valid, "armor": 0},
            "non-string stanza": {**valid, "stanza_types": [None]},
            "wrong stanza type": {**valid, "stanza_types": ["X25519"]},
            "missing stanza": {**valid, "stanza_types": []},
            "extra stanza": {
                **valid,
                "stanza_types": ["mlkem768x25519", "mlkem768x25519"],
            },
            "boolean size": {
                **valid,
                "sizes": {**valid_sizes, "header": True},
            },
            "missing size": {
                **valid,
                "sizes": {
                    key: value for key, value in valid_sizes.items() if key != "header"
                },
            },
            "extra size": {
                **valid,
                "sizes": {**valid_sizes, "trailer": 0},
            },
            "negative size": {
                **valid,
                "sizes": {**valid_sizes, "header": -1},
            },
            "unknown member": {**valid, "unknown": True},
        }

        for label, metadata in cases.items():
            with self.subTest(label):
                self.assertFalse(
                    age_inspection_has_exact_postquantum_stanzas(
                        metadata,
                        stanza_count=1,
                    )
                )

    def test_admission_rejects_a_classical_only_ciphertext(self) -> None:
        classical_identity, classical_recipient = self.make_identity(
            "classical-identity.txt",
            postquantum=False,
        )
        candidate = self.encrypt(
            b"classical recipient fixture",
            recipients=[classical_recipient],
        )
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)

        result = self.run_admitter_with(identity=classical_identity)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_admission_requires_each_supplied_identity_to_decrypt(self) -> None:
        missing_identity, _ = self.make_identity("missing-identity.txt")
        _, unauthorized_recipient = self.make_identity("unauthorized-identity.txt")
        candidate = self.encrypt(
            b"recipient substitution fixture",
            recipients=[self.recipient, unauthorized_recipient],
        )
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)

        result = self.run_admitter_with(
            identity=self.identity,
            additional_identities=[missing_identity],
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_v1_admission_rejects_multiple_identities_and_recipients(self) -> None:
        additional_identity, additional_recipient = self.make_identity(
            "additional-identity.txt"
        )
        candidate = self.encrypt(
            b"complete recipient set fixture",
            recipients=[self.recipient, additional_recipient],
        )
        (self.root / "candidate.age").write_bytes(candidate)

        result = self.run_admitter_with(
            identity=self.identity,
            additional_identities=[additional_identity],
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertFalse((self.root / MANIFEST).exists())

    def test_admission_rejects_duplicate_identity_material(self) -> None:
        duplicate_identity = self.base / "duplicate-identity.txt"
        shutil.copyfile(self.identity, duplicate_identity)
        duplicate_identity.chmod(0o600)
        _, unauthorized_recipient = self.make_identity("unauthorized-identity.txt")
        candidate = self.encrypt(
            b"duplicate identity substitution fixture",
            recipients=[self.recipient, unauthorized_recipient],
        )
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)

        result = self.run_admitter_with(
            identity=self.identity,
            additional_identities=[duplicate_identity],
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_admission_rejects_a_group_or_world_readable_identity(self) -> None:
        candidate = self.encrypt(b"identity mode fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)
        self.identity.chmod(0o644)

        result = self.run_admitter()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_admission_rejects_a_symlinked_identity(self) -> None:
        candidate = self.encrypt(b"identity symlink fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)
        symlink = self.base / "identity-link.txt"
        symlink.symlink_to(self.identity)

        result = self.run_admitter_with(identity=symlink)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_admission_rejects_same_version_path_wrappers_before_identity_use(
        self,
    ) -> None:
        (self.root / "candidate.age").write_bytes(b"forged age envelope")
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)
        trusted_age = shutil.which("age")
        self.assertIsNotNone(trusted_age)
        trusted_tooling_directory = Path(trusted_age).parent
        fake_bin = self.base / "same-version-wrappers"
        fake_bin.mkdir()
        identity_capture = self.base / "captured-identity"
        wrapper = textwrap.dedent(
            """\
            #!/bin/sh
            if [ "${1-}" = --version ]; then
              printf '%s\\n' v1.3.1
              exit 0
            fi
            for argument do
              case "$argument" in
                /dev/fd/*) /bin/cat "$argument" >"$MALICIOUS_AGE_IDENTITY_CAPTURE" ;;
              esac
            done
            case "${0##*/}" in
              age-keygen) printf '%s\\n' age1pq1attackercontrolled ;;
              age-inspect)
                printf '%s\\n' '{"version":"age-encryption.org/v1","postquantum":"yes","armor":false,"stanza_types":["mlkem768x25519"],"sizes":{"header":1,"armor":0,"overhead":1,"min_payload":1,"max_payload":1,"min_padding":0,"max_padding":0}}'
                ;;
            esac
            exit 0
            """
        )
        for name in ("age", "age-keygen", "age-inspect"):
            path = fake_bin / name
            path.write_text(wrapper, encoding="utf-8")
            path.chmod(0o755)
        environment = os.environ.copy()
        environment["AGE_TOOLING_DIRECTORY"] = os.fspath(trusted_tooling_directory)
        environment["MALICIOUS_AGE_IDENTITY_CAPTURE"] = os.fspath(identity_capture)
        environment["PATH"] = os.fspath(fake_bin)

        result = self.run_admitter_with(
            identity=self.identity,
            environment=environment,
        )

        self.assertFalse(identity_capture.exists())
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_admission_rejects_a_tooling_authority_inside_the_repository(
        self,
    ) -> None:
        candidate = self.encrypt(b"in-repository tooling authority fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)
        in_repository = self.root / "trusted-age-bin"
        in_repository.mkdir()
        for name in ("age", "age-keygen", "age-inspect"):
            (in_repository / name).symlink_to(self.age_tooling_directory / name)
        outside_symlink = self.base / "trusted-age-bin-link"
        outside_symlink.symlink_to(in_repository, target_is_directory=True)

        for label, tooling_directory in (
            ("lexical", in_repository),
            ("canonical", outside_symlink),
        ):
            with self.subTest(label):
                environment = os.environ.copy()
                environment["AGE_TOOLING_DIRECTORY"] = os.fspath(tooling_directory)

                result = self.run_admitter_with(
                    identity=self.identity,
                    environment=environment,
                )

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertEqual(
                    result.stderr,
                    "age-envelope admission failed\n",
                )
                self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_admission_rejects_external_tooling_symlinked_to_repo_executables(
        self,
    ) -> None:
        (self.root / "candidate.age").write_bytes(b"forged age envelope")
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)
        repository_bin = self.root / "repo-controlled-age-bin"
        repository_bin.mkdir()
        external_bin = self.base / "external-age-bin"
        external_bin.mkdir()
        identity_capture = self.base / "captured-repo-symlink-identity"
        wrapper = textwrap.dedent(
            """\
            #!/bin/sh
            if [ "${1-}" = --version ]; then
              printf '%s\\n' v1.3.1
              exit 0
            fi
            for argument do
              case "$argument" in
                /dev/fd/*) /bin/cat "$argument" >"$MALICIOUS_AGE_IDENTITY_CAPTURE" ;;
              esac
            done
            case "${0##*/}" in
              age-keygen) printf '%s\\n' age1pq1repocontrolled ;;
              age-inspect)
                printf '%s\\n' '{"version":"age-encryption.org/v1","postquantum":"yes","armor":false,"stanza_types":["mlkem768x25519"],"sizes":{"header":1,"armor":0,"overhead":1,"min_payload":1,"max_payload":1,"min_padding":0,"max_padding":0}}'
                ;;
            esac
            exit 0
            """
        )
        for name in ("age", "age-keygen", "age-inspect"):
            repository_tool = repository_bin / name
            repository_tool.write_text(wrapper, encoding="utf-8")
            repository_tool.chmod(0o755)
            (external_bin / name).symlink_to(repository_tool)
        environment = os.environ.copy()
        environment["AGE_TOOLING_DIRECTORY"] = os.fspath(external_bin)
        environment["MALICIOUS_AGE_IDENTITY_CAPTURE"] = os.fspath(identity_capture)
        environment["PATH"] = os.fspath(repository_bin)

        result = self.run_admitter_with(
            identity=self.identity,
            environment=environment,
        )

        self.assertFalse(identity_capture.exists())
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_admission_rejects_matching_ambient_executables_inside_repository(
        self,
    ) -> None:
        candidate = self.encrypt(b"repository ambient tooling fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)
        repository_bin = self.root / "matching-age-bin"
        repository_bin.mkdir()
        for name in ("age", "age-keygen", "age-inspect"):
            shutil.copy2(self.age_tooling_directory / name, repository_bin / name)
        environment = os.environ.copy()
        environment["AGE_TOOLING_DIRECTORY"] = os.fspath(self.age_tooling_directory)
        environment["PATH"] = os.fspath(repository_bin)

        result = self.run_admitter_with(
            identity=self.identity,
            environment=environment,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_admission_rejects_incomplete_or_trailing_envelopes_without_mutation(
        self,
    ) -> None:
        native = self.encrypt(b"x" * 2048)
        inspected = subprocess.run(
            ["age-inspect", "--json", "-"],
            input=native,
            check=True,
            capture_output=True,
            timeout=TOOL_TIMEOUT_SECONDS,
        )
        header_size = json.loads(inspected.stdout)["sizes"]["header"]
        accepted_truncation = native[: header_size + 32]
        self.assertEqual(
            subprocess.run(
                ["age-inspect", "--json", "-"],
                input=accepted_truncation,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=TOOL_TIMEOUT_SECONDS,
            ).returncode,
            0,
        )
        credential = b"ghp_" + b"A" * 36
        cases = {
            "appended plaintext": native + b"\n" + credential + b"\n",
            "accepted truncation": accepted_truncation,
            "concatenated streams": native + native,
            "re-armored truncation": self.armor(accepted_truncation),
        }
        sentinel = manifest_bytes([])

        for label, candidate in cases.items():
            with self.subTest(label):
                (self.root / "candidate.age").write_bytes(candidate)
                (self.root / MANIFEST).write_bytes(sentinel)

                result = self.run_admitter()

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "age-envelope admission failed\n")
                self.assertNotIn(credential.decode("ascii"), result.stderr)
                self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_scanner_rejects_a_noncanonical_or_symlinked_manifest(self) -> None:
        native = self.encrypt(b"manifest fixture")
        (self.root / "candidate.age").write_bytes(native)
        canonical = manifest_bytes([("candidate.age", native)])
        outside = self.base / "outside-manifest.json"
        outside.write_bytes(canonical)
        manifest = self.root / MANIFEST
        cases: dict[str, bytes | None] = {
            "missing": None,
            "duplicate member": canonical.replace(
                b'{\n  "version":',
                b'{\n  "version": "privacy-age-envelopes/v1",\n  "version":',
                1,
            ),
            "noncanonical encoding": json.dumps(
                json.loads(canonical), separators=(",", ":")
            ).encode("ascii"),
            "unknown member": canonical.replace(
                b'{\n  "version":', b'{\n  "unknown": true,\n  "version":', 1
            ),
            "traversal path": canonical.replace(
                b'"candidate.age"', b'"../candidate.age"'
            ),
            "uppercase digest": canonical.replace(b"sha256:", b"SHA256:", 1),
        }

        for label, data in cases.items():
            with self.subTest(label):
                manifest.unlink(missing_ok=True)
                if data is not None:
                    manifest.write_bytes(data)
                result = self.run_scanner()
                self.assertEqual(result.returncode, 1)
                self.assertIn(
                    f"{MANIFEST}:0: [invalid-age-envelope-manifest]",
                    result.stdout,
                )

        manifest.unlink(missing_ok=True)
        manifest.symlink_to(outside)
        result = self.run_scanner()
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{MANIFEST}:0: [invalid-age-envelope-manifest]", result.stdout)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs require POSIX")
    def test_scanner_rejects_a_fifo_manifest_without_blocking(self) -> None:
        os.mkfifo(self.root / MANIFEST)

        result = self.run_scanner()

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"{MANIFEST}:0: [invalid-age-envelope-manifest]",
            result.stdout,
        )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs require POSIX")
    def test_admission_rejects_a_fifo_candidate_without_manifest_mutation(
        self,
    ) -> None:
        os.mkfifo(self.root / "candidate.age")
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)

        result = self.run_admitter()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_admission_preserves_the_manifest_and_hides_replace_errors(self) -> None:
        candidate = self.encrypt(b"manifest replacement fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)
        hook_directory = self.base / "python-hook"
        hook_directory.mkdir()
        sensitive_error = os.fspath(self.base / "private-replace-detail")
        (hook_directory / "sitecustomize.py").write_text(
            textwrap.dedent(
                f"""
                import os

                _original_replace = os.replace

                def _replace(source, destination):
                    if os.path.basename(os.fspath(destination)) == {MANIFEST!r}:
                        raise OSError({sensitive_error!r})
                    return _original_replace(source, destination)

                os.replace = _replace
                """
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(
                None,
                [
                    os.fspath(hook_directory),
                    environment.get("PYTHONPATH", ""),
                ],
            )
        )

        result = self.run_admitter_with(
            identity=self.identity,
            environment=environment,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertNotIn(sensitive_error, result.stderr)
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)
        self.assertEqual(
            list(self.root.glob(f"{MANIFEST}.*")),
            [],
        )

    def test_admission_hides_an_identity_stat_race_and_preserves_manifest(self) -> None:
        candidate = self.encrypt(b"identity stat race fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)
        hook_directory = self.base / "identity-stat-hook"
        hook_directory.mkdir()
        sensitive_error = os.fspath(self.base / "private-identity-stat-detail")
        (hook_directory / "sitecustomize.py").write_text(
            textwrap.dedent(
                f"""
                import os
                from pathlib import Path

                _original_stat = Path.stat

                def _stat(path, *args, **kwargs):
                    if os.fspath(path) == {os.fspath(self.identity.resolve())!r}:
                        raise OSError({sensitive_error!r})
                    return _original_stat(path, *args, **kwargs)

                Path.stat = _stat
                """
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(
                None,
                [os.fspath(hook_directory), environment.get("PYTHONPATH", "")],
            )
        )

        result = self.run_admitter_with(
            identity=self.identity,
            environment=environment,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "age-envelope admission failed\n")
        self.assertNotIn(sensitive_error, result.stderr)
        self.assertEqual((self.root / MANIFEST).read_bytes(), sentinel)

    def test_admission_fsyncs_the_manifest_directory_after_replacement(self) -> None:
        candidate = self.encrypt(b"directory durability fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        hook_directory = self.base / "directory-fsync-hook"
        hook_directory.mkdir()
        marker = self.base / "directory-fsynced"
        (hook_directory / "sitecustomize.py").write_text(
            textwrap.dedent(
                f"""
                import os
                import stat

                _original_fsync = os.fsync

                def _fsync(descriptor):
                    if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                        with open({os.fspath(marker)!r}, "w", encoding="utf-8") as stream:
                            stream.write("directory fsynced\\n")
                    return _original_fsync(descriptor)

                os.fsync = _fsync
                """
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(
                None,
                [os.fspath(hook_directory), environment.get("PYTHONPATH", "")],
            )
        )

        result = self.run_admitter_with(
            identity=self.identity,
            environment=environment,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "directory fsynced\n")

    def test_admission_sets_manifest_mode_through_the_open_descriptor(self) -> None:
        candidate = self.encrypt(b"descriptor mode fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        hook_directory = self.base / "manifest-chmod-hook"
        hook_directory.mkdir()
        (hook_directory / "sitecustomize.py").write_text(
            textwrap.dedent(
                f"""
                import os
                from pathlib import Path

                _original_chmod = Path.chmod

                def _chmod(path, *args, **kwargs):
                    if os.path.basename(os.fspath(path)).startswith({MANIFEST!r} + "."):
                        raise OSError("pathname chmod must not be used")
                    return _original_chmod(path, *args, **kwargs)

                Path.chmod = _chmod
                """
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(
                None,
                [os.fspath(hook_directory), environment.get("PYTHONPATH", "")],
            )
        )

        result = self.run_admitter_with(
            identity=self.identity,
            environment=environment,
        )

        manifest = self.root / MANIFEST
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o644)

    def test_admission_reports_durability_uncertain_after_directory_fsync_failure(
        self,
    ) -> None:
        candidate = self.encrypt(b"directory fsync failure fixture")
        (self.root / "candidate.age").write_bytes(candidate)
        sentinel = manifest_bytes([])
        (self.root / MANIFEST).write_bytes(sentinel)
        hook_directory = self.base / "directory-fsync-failure-hook"
        hook_directory.mkdir()
        sensitive_error = os.fspath(self.base / "private-directory-fsync-detail")
        (hook_directory / "sitecustomize.py").write_text(
            textwrap.dedent(
                f"""
                import os
                import stat

                _original_fsync = os.fsync

                def _fsync(descriptor):
                    if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                        raise OSError({sensitive_error!r})
                    return _original_fsync(descriptor)

                os.fsync = _fsync
                """
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(
                None,
                [os.fspath(hook_directory), environment.get("PYTHONPATH", "")],
            )
        )

        result = self.run_admitter_with(
            identity=self.identity,
            environment=environment,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr,
            "age-envelope manifest durability uncertain\n",
        )
        self.assertNotIn(sensitive_error, result.stderr)
        self.assertEqual(
            (self.root / MANIFEST).read_bytes(),
            manifest_bytes([("candidate.age", candidate)]),
        )
        self.assertEqual(list(self.root.glob(f"{MANIFEST}.*")), [])

    def test_scanner_rejects_a_case_confusable_age_suffix(self) -> None:
        data = self.encrypt(b"renamed ciphertext")
        (self.root / "candidate.AgE").write_bytes(data)

        result = self.run_scanner()

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "candidate.AgE:0: [invalid-age-envelope-suffix] review required",
            result.stdout,
        )
        self.assertIn("[invalid-age-envelope-manifest]", result.stdout)

    def test_scanner_inventory_does_not_hide_age_files_in_cache_named_directories(
        self,
    ) -> None:
        credential = "gh" + "p_" + "A" * 36
        private_key = "-----BEGIN " + "PRIVATE KEY-----"
        hidden = {
            ".pytest_cache/credential.age": credential,
            "__pycache__/private-key.age": private_key,
        }
        for relative, contents in hidden.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents + "\n", encoding="utf-8")

        result = self.run_scanner()

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{MANIFEST}:0: [invalid-age-envelope-manifest]", result.stdout)
        self.assertIn(".pytest_cache/credential.age:1: [provider-token]", result.stdout)
        self.assertIn("__pycache__/private-key.age:1: [private-key]", result.stdout)
        self.assertNotIn(credential, result.stdout + result.stderr)
        self.assertNotIn(private_key, result.stdout + result.stderr)

    def test_admission_includes_age_files_in_cache_named_directories(self) -> None:
        relative = ".pytest_cache/candidate.age"
        ciphertext = self.encrypt(b"cache inventory fixture")
        candidate = self.root / relative
        candidate.parent.mkdir()
        candidate.write_bytes(ciphertext)

        result = self.run_admitter()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            (self.root / MANIFEST).read_bytes(),
            manifest_bytes([(relative, ciphertext)]),
        )

    def test_age_discovery_fails_closed_on_a_walk_error(self) -> None:
        error = PermissionError("private path")

        def failed_walk(*args: object, **kwargs: object) -> object:
            callback = kwargs.get("onerror")
            if callback is None and len(args) > 2:
                callback = args[2]
            self.assertIsNotNone(callback)
            assert callable(callback)
            callback(error)
            return ()

        with (
            mock.patch("scripts.privacy_age_envelopes.os.walk", failed_walk),
            self.assertRaises(AgeEnvelopeError),
        ):
            discover_age_files(self.root)

    def test_canonical_manifest_rejects_a_serialization_above_its_bound(
        self,
    ) -> None:
        digest = "sha256:" + "a" * 64
        path_prefix = "a" * 480
        entry_count = 1
        while True:
            entries = {
                f"{path_prefix}{index:04d}.age": digest for index in range(entry_count)
            }
            document = {
                "version": MANIFEST_VERSION,
                "envelopes": [
                    {"path": path, "sha256": entries[path]} for path in sorted(entries)
                ],
            }
            serialized = (
                json.dumps(document, ensure_ascii=True, indent=2) + "\n"
            ).encode("ascii")
            if len(serialized) > MAX_AGE_MANIFEST_BYTES:
                break
            entry_count *= 2

        self.assertGreater(len(serialized), MAX_AGE_MANIFEST_BYTES)
        with self.assertRaises(AgeEnvelopeError):
            canonical_manifest_bytes(entries)

    def test_scanner_rejects_an_age_symlink_without_following_it(self) -> None:
        outside = self.base / "outside.age"
        outside.write_bytes(self.encrypt(b"outside ciphertext"))
        (self.root / "candidate.age").symlink_to(outside)

        result = self.run_scanner()

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "candidate.age:0: [age-envelope-not-regular] review required",
            result.stdout,
        )

    def test_admission_rejects_unsafe_boundaries_without_manifest_mutation(
        self,
    ) -> None:
        native = self.encrypt(b"boundary fixture")
        candidate = self.root / "candidate.age"
        candidate.write_bytes(native)
        manifest = self.root / MANIFEST
        sentinel = manifest_bytes([])

        inside_identity = self.root / "identity.txt"
        inside_identity.write_bytes(self.identity.read_bytes())
        manifest.write_bytes(sentinel)
        result = self.run_admitter_with(identity=inside_identity)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(manifest.read_bytes(), sentinel)

        outside = self.base / "outside.age"
        outside.write_bytes(native)
        candidate.unlink()
        candidate.symlink_to(outside)
        result = self.run_admitter()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(manifest.read_bytes(), sentinel)

        candidate.unlink()
        (self.root / "candidate.AGE").write_bytes(native)
        result = self.run_admitter()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(manifest.read_bytes(), sentinel)

        (self.root / "candidate.AGE").unlink()
        candidate.write_bytes(b"x" * (MAX_AGE_ENVELOPE_BYTES + 1))
        result = self.run_admitter()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(manifest.read_bytes(), sentinel)

        fake_bin = self.base / "fake-bin"
        fake_bin.mkdir()
        fake_age = fake_bin / "age"
        fake_age.write_text(
            "#!/bin/sh\nprintf '%s\\n' v9.9.9\n",
            encoding="utf-8",
        )
        fake_age.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = os.fspath(fake_bin)
        candidate.write_bytes(native)
        result = self.run_admitter_with(
            identity=self.identity,
            environment=environment,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(manifest.read_bytes(), sentinel)
